from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import AsyncIterator

from app.agent.after_sale_policy import AfterSalePolicyService
from app.agent.budget_planner import BudgetPlanner
from app.agent.conversation_mode import ConversationModeRouter
from app.agent.cart import CartService
from app.agent.constraint_parser import ConstraintParser
from app.agent.grounding_guard import GroundingGuard
from app.agent.intent_rules import IntentRules
from app.agent.llm_output_sanitizer import LLMOutputSanitizer
from app.agent.product_qa import ProductQAService
from app.agent.recommendation_cache import RecommendationCache
from app.agent.session_store import SessionStore
from app.agent.travel_intent import parse_travel_context
from app.agent.user_profile import UserProfileService
from app.agent.weather_service import WeatherService
from app.llm.gateway import LLMGateway
from app.llm.schemas import ConstraintInput, ConstraintOutput
from app.models.schemas import ChatRequest
from app.observability import observability
from app.rag.product_repository import ProductRepository, SearchConstraints
from app.recovery import empty_recommendation_notice, notice
from app.travel.travel_need_planner import TravelBundle, TravelNeedPlanner


@dataclass(frozen=True)
class RecommendationReply:
    text: str
    source: str


class AgentOrchestrator:
    def __init__(
        self,
        products: ProductRepository,
        cart: CartService,
        sessions: SessionStore,
        profiles: UserProfileService | None = None,
    ) -> None:
        self.products = products
        self.cart = cart
        self.sessions = sessions
        self.parser = ConstraintParser()
        self.intent = IntentRules()
        self.llm = LLMGateway()
        self.guard = GroundingGuard()
        self.output_sanitizer = LLMOutputSanitizer(self.guard)
        self.reply_cache = RecommendationCache()
        self.profiles = profiles or UserProfileService()
        self.planner = BudgetPlanner(products, self.parser, self.profiles)
        self.travel_planner = TravelNeedPlanner(products, self.parser)
        self.after_sale = AfterSalePolicyService()
        self.mode_router = ConversationModeRouter()
        self.weather = WeatherService()
        self.product_qa = ProductQAService()

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[str]:
        trace_id = observability.start_trace(
            "chat",
            {"session_id": request.session_id, "message": request.message},
        )
        trace_token = observability.set_current_trace(trace_id)
        started_at = time.perf_counter()
        first_token_seen = False
        try:
            async for event in self._handle(request):
                if event["event"] == "token" and not first_token_seen:
                    first_token_seen = True
                    first_token_ms = (time.perf_counter() - started_at) * 1000
                    observability.record_latency("sse_first_token_latency_ms", first_token_ms)
                    observability.add_current_step("sse_first_token", {"latency_ms": round(first_token_ms, 2)})
                if event["event"] == "done" and isinstance(event.get("data"), dict):
                    event = {**event, "data": {**event["data"], "trace_id": trace_id}}
                self._record_stream_event(event)
                yield f"event: {event['event']}\n"
                yield f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            observability.finish_trace(trace_id, "ok")
        except Exception as exc:
            observability.add_current_step("error", {"message": str(exc)})
            observability.finish_trace(trace_id, "error")
            fallback = notice("chat_exception")
            yield "event: fallback\n"
            yield f"data: {fallback.model_dump_json()}\n\n"
            yield "event: done\n"
            yield f"data: {json.dumps({'ok': False, 'trace_id': trace_id}, ensure_ascii=False)}\n\n"
        finally:
            observability.reset_current_trace(trace_token)

    async def _handle(self, request: ChatRequest) -> AsyncIterator[dict]:
        message = request.message.strip()
        session = self.sessions.get(request.session_id)
        lowered = message.lower()

        if self.intent.is_profile_clear(message):
            profile = self.profiles.clear(request.session_id)
            session.pending_constraints = None
            session.pending_clarification = None
            session.constraints = self.parser.parse("")
            observability.increment("profile_clears")
            observability.add_current_step("profile", {"action": "clear"})
            async for token in self._tokens("已清除你的长期偏好，后续推荐会重新按当前对话条件判断。"):
                yield {"event": "token", "data": token}
            yield {"event": "profile", "data": profile.model_dump()}
            yield {"event": "done", "data": {"ok": True}}
            return

        if self.intent.is_profile_view(message):
            profile = self.profiles.get(request.session_id)
            observability.increment("profile_views")
            observability.add_current_step("profile", {"action": "view", "profile": profile.model_dump()})
            async for token in self._tokens(self._profile_summary(profile)):
                yield {"event": "token", "data": token}
            yield {"event": "profile", "data": profile.model_dump()}
            yield {"event": "done", "data": {"ok": True}}
            return

        if self.intent.is_profile_remember(message):
            profile, updates = self.profiles.remember_from_message(request.session_id, message)
            observability.increment("profile_updates")
            observability.add_current_step("profile", {"action": "remember", "updates": updates, "profile": profile.model_dump()})
            text = "我已经记住：" + "、".join(updates) + "。之后相关类目的推荐会自动带上这些偏好。" if updates else "这句话里我没有识别到可长期保存的预算、肤质、品牌或成分偏好。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "profile", "data": profile.model_dump()}
            yield {"event": "done", "data": {"ok": True}}
            return

        smalltalk = self._smalltalk_response(message)
        if smalltalk:
            observability.increment("smalltalk_turns")
            observability.add_current_step("conversation_mode", {"mode": "general_chat", "intent_level": 0, "reason": "deterministic smalltalk"})
            async for token in self._tokens(smalltalk):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": {"ok": True, "mode": "general_chat"}}
            return

        mode = self.mode_router.route(
            message,
            has_last_products=bool(session.last_product_ids),
            has_pending_clarification=bool(session.pending_clarification),
            has_active_shopping_context=bool(session.constraints.category),
        )
        observability.add_current_step(
            "conversation_mode",
            {
                "mode": mode.mode,
                "intent_level": mode.shopping_intent_level,
                "need_rag": mode.need_rag,
                "need_product_cards": mode.need_product_cards,
                "need_tool_call": mode.need_tool_call,
                "reason": mode.reason,
            },
        )
        if mode.mode == "general_chat":
            observability.increment("general_chat_turns")
            async for event in self._handle_general_chat(request.session_id, message):
                yield event
            return
        if mode.mode == "weather_query":
            observability.increment("weather_turns")
            async for event in self._handle_weather(message):
                yield event
            return
        if mode.mode == "product_knowledge":
            observability.increment("product_knowledge_turns")
            async for event in self._handle_product_knowledge(request.session_id, message):
                yield event
            return
        if mode.mode == "weak_purchase_intent":
            observability.increment("weak_purchase_intents")
            text = self._weak_purchase_prompt(message)
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": {"ok": True, "mode": "weak_purchase_intent", "needs_clarification": True}}
            return

        if self.intent.is_compare(lowered):
            observability.increment("compare_intents")
            observability.add_current_step("intent", {"name": "compare", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_compare(message, session.last_product_ids):
                yield event
            return

        if self.intent.is_cart(lowered):
            observability.increment("cart_intents")
            observability.add_current_step("intent", {"name": "cart", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_cart(request.session_id, message, session.last_product_ids):
                yield event
            return

        if self.intent.is_feedback(message, session.last_product_ids):
            observability.increment("feedback_intents")
            observability.add_current_step("intent", {"name": "feedback", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_feedback(request.session_id, message, session.last_product_ids):
                yield event
            return

        if self.intent.is_after_sale(message):
            observability.increment("after_sale_policy_intents")
            observability.add_current_step("intent", {"name": "after_sale_policy", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_after_sale_policy(message, session.last_product_ids):
                yield event
            return

        if self.intent.is_product_qa(message, session.last_product_ids):
            observability.increment("product_qa_intents")
            observability.add_current_step("intent", {"name": "product_qa", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_product_qa(message, session.last_product_ids):
                yield event
            return

        if self.planner.can_plan(message):
            observability.increment("budget_plan_intents")
            observability.add_current_step("intent", {"name": "budget_plan"})
            profile, profile_updates = self.profiles.remember_scenario_from_message(request.session_id, message)
            plan = await asyncio.to_thread(self.planner.build, request.session_id, message)
            products = [item.product for item in plan.items] if plan else []
            session.pending_constraints = None
            session.pending_clarification = None
            session.constraints = self.parser.parse(message)
            session.last_product_ids = [product.product_id for product in products]
            text = self._plan_intro(plan, profile_updates) if plan else "我暂时没能在商品库里配出完整方案，可以放宽预算或类目后再试。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            if plan:
                yield {"event": "plan", "data": plan.model_dump()}
                yield {"event": "products", "data": [product.model_dump() for product in products]}
                yield {"event": "profile", "data": profile.model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
            return

        if self._is_travel_packing_intent(message):
            observability.increment("travel_bundle_intents")
            travel = parse_travel_context(message)
            observability.add_current_step(
                "intent",
                {
                    "name": "travel_bundle",
                    "destination": travel.destination,
                    "scenario": travel.scenario,
                },
            )
            travel_plan = await self.llm.travel_need_plan(message, session_id=request.session_id)
            weather_context = await self.weather.lookup(travel.destination) if travel.destination else None
            bundle = self.travel_planner.build(message, travel_plan, weather_context=weather_context)
            products = list(bundle.products)
            previous_constraints = session.pending_constraints or session.constraints
            previous_phone_context = (
                previous_constraints.category == "数码电子"
                and previous_constraints.sub_category in {"手机", "智能手机"}
            )
            session.pending_constraints = None
            session.pending_clarification = None
            session.constraints = self.parser.parse(f"{travel.query_prefix} 户外 防晒 快充 轻量")
            session.last_product_ids = [product.product_id for product in products]
            text = self._travel_bundle_intro(message, previous_phone_context, travel_plan, bundle, weather_context)
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            if weather_context:
                yield {"event": "weather", "data": weather_context.model_dump()}
            yield {
                "event": "travel_plan",
                "data": {
                    "destination": bundle.context.destination,
                    "attributes": list(bundle.context.attributes),
                    "activities": list(bundle.context.likely_activities),
                    "risks": list(bundle.context.risks),
                    "packing_needs": list(bundle.context.packing_needs),
                    "scenes": list(bundle.scene_names),
                    "needs": [
                        {
                            "need": need.need,
                            "category": need.category,
                            "sub_category": need.sub_category,
                            "reason": need.reason,
                        }
                        for need in bundle.needs[:6]
                    ],
                },
            }
            yield {"event": "products", "data": [product.model_dump() for product in products]}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
            return

        parsed_constraints = self.parser.parse(message)
        parsed_constraints = await self._refine_constraints_with_llm(request.session_id, message, session, parsed_constraints)
        base_constraints = self._base_constraints_for_message(session, parsed_constraints)
        constraints = self.parser.merge(base_constraints, parsed_constraints)
        constraints = self.profiles.apply_to_constraints(request.session_id, constraints, message=message)
        observability.add_current_step(
            "constraint_parser",
            {
                "parsed": self._constraints_payload(parsed_constraints),
                "merged": self._constraints_payload(constraints),
            },
        )

        clarification = self._clarification_prompt(message, constraints, parsed_constraints)
        if clarification:
            observability.increment("clarification_turns")
            observability.add_current_step(
                "active_clarification",
                {"prompt": clarification, "constraints": self._constraints_payload(constraints)},
            )
            session.pending_constraints = constraints
            session.pending_clarification = clarification
            session.last_product_ids = []
            async for token in self._tokens(clarification):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist", "needs_clarification": True}}
            return

        session.pending_constraints = None
        session.pending_clarification = None
        session.constraints = constraints
        retrieved_products = await self._search_products(message, constraints, limit=12)
        products = self._business_rank_products(message, constraints, retrieved_products)[:5]
        session.last_product_ids = [product.product_id for product in products]

        if not products:
            observability.increment("empty_recommendations")
            observability.add_current_step("recommendation_results", {"count": 0, "product_ids": []})
            text = "我在当前商品库里没有找到完全符合条件的商品。可以放宽预算、品牌或排除条件后再试一次。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "fallback", "data": empty_recommendation_notice(text, constraints).model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
            return

        observability.increment("recommendation_turns")
        observability.add_current_step(
            "recommendation_results",
            {"count": len(products), "product_ids": [product.product_id for product in products[:5]]},
        )
        reply = await self._cached_response_text(request.session_id, message, products, constraints)
        has_streamed_tokens = False
        if not reply:
            fallback = RecommendationReply(self._fallback_response_text(message, products[:3], constraints), "fallback")
            streamed_chunks: list[str] = []
            pending = ""
            emitted_prefix = False
            answer_started = False
            stream_blocked = False
            async for chunk in self.llm.stream_recommendation_reply(message, products, constraints, session_id=request.session_id):
                if not emitted_prefix:
                    prefix = "以下信息来自本地商品库。"
                    async for token in self._tokens(prefix):
                        has_streamed_tokens = True
                        yield {"event": "token", "data": token}
                    streamed_chunks.append(prefix)
                    emitted_prefix = True
                pending += chunk
                if not answer_started:
                    answer_start = self.output_sanitizer.answer_start_index(pending)
                    if answer_start is None:
                        if self.output_sanitizer.is_internal_review_segment(pending):
                            pending = ""
                        elif len(pending) < 260:
                            continue
                        else:
                            answer_started = True
                    else:
                        pending = pending[answer_start:]
                        answer_started = True
                        if not pending:
                            continue
                if not self.output_sanitizer.should_flush_stream_segment(pending):
                    continue
                if self.output_sanitizer.is_internal_review_segment(pending):
                    pending = ""
                    continue
                if not self.output_sanitizer.is_safe_stream_segment("".join(streamed_chunks), pending, products, constraints):
                    stream_blocked = True
                    break
                streamed_chunks.append(pending)
                has_streamed_tokens = True
                yield {"event": "token", "data": pending}
                pending = ""
            if pending and not stream_blocked:
                if not answer_started:
                    answer_start = self.output_sanitizer.answer_start_index(pending)
                    if answer_start is not None:
                        pending = pending[answer_start:]
                if self.output_sanitizer.is_internal_review_segment(pending):
                    pending = ""
                elif self.output_sanitizer.is_safe_stream_segment("".join(streamed_chunks), pending, products, constraints):
                    streamed_chunks.append(pending)
                    has_streamed_tokens = True
                    yield {"event": "token", "data": pending}
                else:
                    stream_blocked = True
            streamed_text = "".join(streamed_chunks)
            if stream_blocked:
                observability.increment("llm_stream_guard_failures")
                observability.add_current_step("llm_stream_guard", {"valid": False, "mode": "segment_blocked"})
                reply = fallback
                async for token in self._tokens("\n" + fallback.text):
                    has_streamed_tokens = True
                    yield {"event": "token", "data": token}
            elif streamed_text:
                guarded = self.guard.validate(streamed_text, products, constraints)
                if guarded:
                    guarded = self.output_sanitizer.strip_internal_review_text(guarded)
                    reply = RecommendationReply(guarded, "llm")
                    self.reply_cache.set(
                        self._recommendation_cache_key(request.session_id, message, products, constraints),
                        guarded,
                        "llm",
                    )
                else:
                    observability.increment("llm_stream_guard_failures")
                    observability.add_current_step("llm_stream_guard", {"valid": False, "mode": "final_blocked"})
                    reply = fallback
                    async for token in self._tokens("\n" + fallback.text):
                        has_streamed_tokens = True
                        yield {"event": "token", "data": token}
            else:
                reply = await self._response_text(request.session_id, message, products, constraints)
        if not has_streamed_tokens:
            async for token in self._tokens(reply.text):
                yield {"event": "token", "data": token}
        display_products = self._display_products_for_response(reply, products)
        session.last_product_ids = [product.product_id for product in display_products]
        yield {"event": "products", "data": [product.model_dump() for product in display_products]}
        if reply.source == "fallback" and self.llm.status(request.session_id).configured:
            yield {"event": "fallback", "data": notice("model_unavailable").model_dump()}
        yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}

    def _base_constraints_for_message(self, session, parsed_constraints):
        base_constraints = session.pending_constraints or session.constraints
        if parsed_constraints.category and base_constraints.category and parsed_constraints.category != base_constraints.category:
            return parsed_constraints
        if parsed_constraints.category and parsed_constraints.sub_category:
            return parsed_constraints
        return base_constraints

    async def _search_products(self, query: str, constraints: SearchConstraints, limit: int = 5):
        return await asyncio.to_thread(self.products.search, query, constraints, limit)

    async def _refine_constraints_with_llm(self, session_id: str, message: str, session, parsed_constraints) -> object:
        if not self.llm.status(session_id).configured:
            return parsed_constraints
        output = await self.llm.parse_constraints(
            ConstraintInput(
                user_message=message,
                current_constraints=self._constraints_payload(session.pending_constraints or session.constraints),
            ),
            session_id=session_id,
        )
        if not output:
            return parsed_constraints
        refined = self._merge_llm_constraints(parsed_constraints, output)
        observability.add_current_step(
            "llm_constraint_refinement",
            {
                "model_output": output.model_dump(),
                "refined": self._constraints_payload(refined),
            },
        )
        return refined

    def _merge_llm_constraints(self, parsed_constraints, output: ConstraintOutput):
        allowed_categories = {"美妆护肤", "数码电子", "服饰运动", "食品饮料"}
        category = parsed_constraints.category
        if not category and output.category in allowed_categories:
            category = output.category
        sub_category = parsed_constraints.sub_category or self._clean_llm_text(output.sub_category)
        include_terms = list(dict.fromkeys(parsed_constraints.include_terms + self._clean_llm_list(output.include_preferences)))
        exclude_terms = list(dict.fromkeys(parsed_constraints.exclude_terms + self._clean_llm_list(output.exclude_terms)))
        exclude_brands = list(dict.fromkeys(parsed_constraints.exclude_brands + self._clean_llm_list(output.exclude_brands)))
        return SearchConstraints(
            category=category,
            sub_category=sub_category,
            max_price=parsed_constraints.max_price if parsed_constraints.max_price is not None else output.price_max,
            min_price=parsed_constraints.min_price if parsed_constraints.min_price is not None else output.price_min,
            include_terms=include_terms[:8],
            exclude_terms=exclude_terms[:8],
            exclude_brands=exclude_brands[:6],
        )

    def _clean_llm_list(self, values: list[str]) -> list[str]:
        return [value for value in (self._clean_llm_text(value) for value in values) if value][:8]

    def _clean_llm_text(self, value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text or text.lower() in {"null", "none", "不限", "无"}:
            return None
        return text[:24]

    def _business_rank_products(self, message: str, constraints, products):
        active_groups = self._active_feature_groups(message, constraints)
        if not active_groups or not products:
            return products
        scored = []
        for index, product in enumerate(products):
            text = self._product_text_for_business(product)
            score = 0
            for terms in active_groups:
                score += sum(1 for term in terms if term.lower() in text)
            scored.append((score, index, product))
        matching = [item for item in scored if item[0] > 0]
        if len(matching) >= 3:
            ranked = matching
        elif matching:
            ranked = scored
        else:
            return products
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [product for _, _, product in ranked]

    def _active_feature_groups(self, message: str, constraints) -> list[list[str]]:
        compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
        include_text = "".join(str(term).lower() for term in constraints.include_terms)
        haystack = compact + include_text
        feature_groups = {
            "续航": ["续航", "大电池", "电池", "省电", "功耗"],
            "拍照": ["拍照", "影像", "摄影", "主摄", "长焦", "人像", "传感器"],
            "游戏": ["游戏", "性能", "散热", "高刷", "芯片", "稳帧"],
            "快充": ["快充", "充电", "功率", "pd", "gan"],
            "油皮": ["油皮", "控油", "清爽", "不黏腻", "水感"],
            "敏感肌": ["敏感肌", "温和", "低刺激", "不含酒精"],
        }
        return [terms for key, terms in feature_groups.items() if key in haystack]

    def _product_text_for_business(self, product) -> str:
        return " ".join(
            [
                product.title,
                product.brand,
                product.category,
                product.sub_category,
                product.reason,
                " ".join(product.highlights),
                " ".join(product.evidence),
            ]
        ).lower()

    def _is_travel_packing_intent(self, message: str) -> bool:
        return parse_travel_context(message).is_packing_request

    def _travel_bundle_intro(
        self,
        message: str,
        previous_phone_context: bool,
        travel_plan: dict | None = None,
        bundle: TravelBundle | None = None,
        weather_context=None,
    ) -> str:
        travel = parse_travel_context(message)
        suffix = "不会沿用上一轮手机偏好。" if previous_phone_context else "不会把它误判成单品手机需求。"
        if bundle:
            attrs = "、".join(bundle.context.attributes[:5])
            needs = "、".join(need.need for need in bundle.needs[:5])
            clarification = f"{bundle.clarification} " if bundle.clarification else ""
            weather_text = ""
            if weather_context:
                tags = "、".join(weather_context.implications.tags[:3])
                if tags:
                    weather_text = f"我也参考了实时天气标签：{tags}。"
            return (
                f"{clarification}我先按{bundle.context.travel_type}理解，再把{bundle.context.destination}归因为：{attrs}。"
                f"{weather_text}再按{needs}做类目配额检索，每类只挑代表商品，{suffix}"
            )
        focus = str(travel_plan.get("intro_focus") or "").strip() if travel_plan else ""
        if focus and self._is_sentence_like_focus(focus):
            focus = self._focus_from_travel_slots(travel_plan)
        if not focus:
            if any(term in travel.scenario for term in ["高原", "干燥"]):
                focus = "高倍防晒、保湿修护、防风轻量衣物、长途补能和充电"
            elif "寒冷" in travel.scenario:
                focus = "防晒保湿、保暖/防风衣物、补能和充电"
            elif "海边" in travel.scenario:
                focus = "防水防晒、轻量衣物、补能和充电"
            else:
                focus = "防晒、防风轻量衣物、补能和充电"
        return f"{travel.destination}这种{travel.scenario}场景，我按{focus}来配，{suffix}"

    def _is_sentence_like_focus(self, focus: str) -> bool:
        return len(focus) > 36 or any(mark in focus for mark in "，。！？,.!?；;") or any(
            term in focus for term in ["因为", "由于", "需要", "需注意", "适合", "地域", "气候"]
        )

    def _focus_from_travel_slots(self, travel_plan: dict | None) -> str:
        if not travel_plan:
            return ""
        roles = []
        for slot in travel_plan.get("slots", [])[:5]:
            if not isinstance(slot, dict):
                continue
            role = str(slot.get("role") or "").strip()
            if role and role not in roles:
                roles.append(role)
        return "、".join(roles[:5])

    async def _handle_general_chat(self, session_id: str, message: str) -> AsyncIterator[dict]:
        text = await self.llm.general_chat(message, mode="general_chat", session_id=session_id)
        if not text:
            text = self._general_chat_fallback(message)
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "done", "data": {"ok": True, "mode": "general_chat"}}

    async def _handle_product_knowledge(self, session_id: str, message: str) -> AsyncIterator[dict]:
        text = await self.llm.general_chat(message, mode="product_knowledge", session_id=session_id)
        if not text:
            text = self._product_knowledge_fallback(message)
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "done", "data": {"ok": True, "mode": "product_knowledge"}}

    async def _handle_weather(self, message: str) -> AsyncIterator[dict]:
        location = self.intent.weather_location(message)
        if not location:
            text = "我需要先知道城市或目的地，才能查询实时天气。你可以直接问“成都今天天气怎么样”或“三亚明天适合户外吗”。"
        else:
            context = await self.weather.lookup(location)
            if context:
                current = context.current
                parts = [f"{context.location.name}当前天气：{current.condition if current else '天气状况未知'}"]
                if current and current.temperature_c is not None:
                    parts.append(f"气温约 {current.temperature_c:.0f}°C")
                if current and current.apparent_temperature_c is not None:
                    parts.append(f"体感约 {current.apparent_temperature_c:.0f}°C")
                if current and current.humidity is not None:
                    parts.append(f"湿度约 {current.humidity:.0f}%")
                if current and current.precipitation_mm is not None:
                    parts.append(f"降水量 {current.precipitation_mm:.1f} mm")
                if current and current.wind_speed_kmh is not None:
                    parts.append(f"风速约 {current.wind_speed_kmh:.0f} km/h")
                tags = "、".join(context.implications.tags[:3])
                suffix = f"天气标签：{tags}。" if tags else ""
                text = "，".join(parts) + f"。数据源：{context.source}，获取时间：{context.fetched_at[:16]}。{suffix}如果你是准备出行，我可以再按这个天气帮你列购物清单。"
            else:
                text = f"我暂时没有查到{location}的实时天气，建议换成更具体的城市名再试，或打开手机天气 App 核对。"
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        if location:
            context = await self.weather.lookup(location)
            if context:
                yield {"event": "weather", "data": context.model_dump()}
        yield {"event": "done", "data": {"ok": True, "mode": "weather_query"}}

    def _general_chat_fallback(self, message: str) -> str:
        compact = re.sub(r"[\s，。！？,.!?]", "", message)
        if any(term in compact for term in ["烦", "累", "压力", "焦虑", "心情不好"]):
            return (
                "听起来你现在状态不太舒服。可以先把问题拆小一点：休息、吃饭、运动或整理环境，选一个最容易做的。"
                "如果后面你确实想找能改善生活状态的东西，再告诉我预算和使用场景，我会再进入导购模式。"
            )
        return "我可以正常聊天，也可以在你有明确购买、比较、预算或加购需求时切换到导购模式。你可以继续说。"

    def _product_knowledge_fallback(self, message: str) -> str:
        compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
        if "spf" in compact or "防晒" in compact:
            return (
                "SPF 主要表示防晒产品延缓晒伤的能力，PA 通常表示对 UVA 防护强度。"
                "日常通勤不一定只看数值，还要看肤感、防水防汗、是否刺激。"
                "如果你之后要挑具体防晒，可以补充肤质、预算和要避开的成分。"
            )
        if "油皮" in compact or "混油皮" in compact:
            return (
                "油皮通常是全脸出油较明显；混油皮多是 T 区出油，两颊正常或偏干。"
                "选护肤或防晒时，油皮更关注清爽控油，混油皮还要避免两颊拔干。"
                "如果要我筛商品，再告诉我预算和是否敏感肌。"
            )
        return "这个问题更像商品/消费知识，我先按知识解释，不会直接推荐商品。你如果要购买，再补充预算、类目和偏好。"

    def _weak_purchase_prompt(self, message: str) -> str:
        compact = re.sub(r"[\s，。！？,.!?]", "", message)
        if any(term in compact for term in ["运动", "跑步", "健身"]):
            return "你是想先从跑步、健身、骑行，还是户外徒步开始？不同运动需要的装备差别很大。如果想低成本入门，我可以按预算友好和实用优先帮你配一套。"
        if any(term in compact for term in ["睡眠", "压力", "烦", "累"]):
            return "我先不直接推商品。你更想改善睡眠、放松情绪、提高工作学习状态，还是改善卧室环境？如果你确认想买东西，我可以再按预算和使用场景筛选。"
        if any(term in compact for term in ["出油", "油皮", "皮肤"]):
            return "脸部出油可能和肤质、天气、清洁频率、作息有关。你可以先确认是全脸出油还是 T 区出油。如果你是想挑护肤品，我可以按预算、是否敏感肌、是否介意酒精或香精来筛。"
        return "我先不急着推荐商品。你可以补充预算、使用场景、对象和不想要的条件；确认有购买需求后，我再进入导购模式。"

    async def _handle_cart(self, session_id: str, message: str, last_product_ids: list[str]) -> AsyncIterator[dict]:
        target_id = self.intent.target_product_id(message, last_product_ids)
        if any(word in message for word in ["结算", "付款", "支付", "下单"]):
            state = self.cart.state(session_id)
            if state.items:
                text = f"当前购物车有 {len(state.items)} 个商品条目，合计约 {state.total_price:.0f} 元。你可以打开右上角购物车进入沙箱结算。"
            else:
                text = "购物车还是空的。先让我推荐商品并加入购物车后，再进入沙箱结算。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "cart", "data": state.model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "transaction"}}
            return
        if "清空" in message:
            state = self.cart.clear(session_id)
            async for token in self._tokens("购物车已经清空。"):
                yield {"event": "token", "data": token}
            yield {"event": "cart", "data": state.model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "transaction"}}
            return
        if not target_id:
            async for token in self._tokens("我还不确定你想操作哪一款商品，可以说“把第一款加到购物车”。"):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": {"ok": True, "mode": "transaction"}}
            return

        quantity = self.intent.quantity(message)
        if any(word in message for word in ["删", "移除", "不要了"]):
            state = self.cart.remove(session_id, target_id)
            text = "已从购物车移除这款商品。"
        elif any(word in message for word in ["改成", "数量", "设为"]):
            state = self.cart.update(session_id, target_id, quantity)
            text = f"已把这款商品数量改为 {quantity}。"
        else:
            state = self.cart.add(session_id, target_id, quantity)
            text = f"已加入购物车，数量 {quantity}。"

        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "cart", "data": state.model_dump()}
        yield {"event": "done", "data": {"ok": True, "mode": "transaction"}}

    async def _handle_feedback(self, session_id: str, message: str, last_product_ids: list[str]) -> AsyncIterator[dict]:
        target_id = self.intent.target_product_id(message, last_product_ids)
        product = self.products.get(target_id) if target_id else None
        if not product:
            async for token in self._tokens("我还不知道你反馈的是哪款商品，可以先让我推荐几款，再说“第一款太贵了”或“换个品牌”。"):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": {"ok": True}}
            return

        feedback = self.intent.feedback_type(message)
        profile = self.profiles.record_feedback(session_id, product.product_id, feedback, message[:80])
        if feedback == "like":
            text = f"收到，我会把你喜欢 {product.brand} 这类商品记到反馈里。你可以继续让我对比、加购，或者说“找更便宜的”。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "profile", "data": profile.model_dump()}
            yield {"event": "done", "data": {"ok": True}}
            return

        mode = {
            "too_expensive": "cheaper",
            "want_premium": "premium",
            "change_brand": "brand_excluded",
            "dislike": "brand_excluded",
        }.get(feedback, "brand_excluded")
        excluded = [product.brand] if mode == "brand_excluded" else []
        alternatives = self.products.alternatives(product.product_id, mode, query=message, excluded_brands=excluded, limit=4)
        session = self.sessions.get(session_id)
        session.last_product_ids = [item.product_id for item in alternatives]
        text = self._feedback_response_text(product, feedback, alternatives)
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "products", "data": [item.model_dump() for item in alternatives]}
        yield {"event": "profile", "data": profile.model_dump()}
        yield {"event": "done", "data": {"ok": True, "feedback": feedback}}

    async def _handle_after_sale_policy(self, message: str, last_product_ids: list[str]) -> AsyncIterator[dict]:
        target_id = self.intent.target_product_id(message, last_product_ids)
        product = self.products.get(target_id) if target_id else None
        text = self.after_sale.answer(product, message)
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        if product:
            yield {"event": "products", "data": [product.model_dump()]}
        yield {"event": "done", "data": {"ok": True, "mode": "product_knowledge", "policy": self.after_sale.payload(product)}}

    async def _handle_compare(self, message: str, last_product_ids: list[str]) -> AsyncIterator[dict]:
        product_ids = last_product_ids[:2]
        products = [product for product_id in product_ids if (product := self.products.get(product_id))]
        if len(products) < 2:
            async for token in self._tokens("我还需要至少两款候选商品才能对比。你可以先让我推荐几款，再说“对比前两款”。"):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
            return

        text = f"我基于商品库字段对比了 {products[0].brand} 和 {products[1].brand} 这两款。"
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "compare", "data": self._compare_payload(products, message)}
        yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}

    async def _handle_product_qa(self, message: str, last_product_ids: list[str]) -> AsyncIterator[dict]:
        target_id = self.intent.target_product_id(message, last_product_ids)
        product = self.products.get(target_id) if target_id else None
        if not product:
            async for token in self._tokens("我还没有可追问的商品。你可以先让我推荐几款，再问第一款的评论、来源或规格。"):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": {"ok": True}}
            return

        rag = self.products.get_rag(product.product_id)
        text = self.product_qa.answer(message, product, rag)
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "products", "data": [product.model_dump()]}
        yield {"event": "done", "data": {"ok": True, "mode": "product_knowledge", "grounded_product_id": product.product_id}}

    def _compare_payload(self, products, message: str) -> dict:
        rows = [
            {
                "dimension": "价格",
                "values": [f"{product.base_price:.0f} 元" for product in products],
                "winner": min(range(len(products)), key=lambda idx: products[idx].base_price),
            },
            {
                "dimension": "类目",
                "values": [f"{product.category} / {product.sub_category}" for product in products],
                "winner": None,
            },
            {
                "dimension": "核心卖点",
                "values": [product.highlights[0] if product.highlights else product.reason for product in products],
                "winner": None,
            },
            {
                "dimension": "规格数量",
                "values": [f"{len(product.skus)} 个 SKU" for product in products],
                "winner": max(range(len(products)), key=lambda idx: len(products[idx].skus)),
            },
        ]
        summary = self._compare_summary(products, message)
        return {
            "products": [product.model_dump() for product in products],
            "rows": rows,
            "summary": summary,
        }

    def _compare_summary(self, products, message: str) -> str:
        cheaper = min(products, key=lambda product: product.base_price)
        if any(term in message for term in ["便宜", "预算", "性价比"]):
            return f"如果你更看重预算，优先选 {cheaper.brand}，它的基础价更低。"
        return f"如果没有更细的偏好，我建议先看 {products[0].brand}：它是上一轮检索里综合匹配度最高的候选。"

    def _feedback_response_text(self, product, feedback: str, alternatives) -> str:
        if feedback == "too_expensive":
            intro = f"收到，{product.title[:18]} 价格约 {product.base_price:.0f} 元，我改按平替逻辑找更低价候选。"
        elif feedback == "want_premium":
            intro = f"收到，我保留 {product.sub_category} 类目，改找更高端/升级款。"
        elif feedback in {"change_brand", "dislike"}:
            intro = f"收到，我先避开 {product.brand}，找同类目替代品。"
        else:
            intro = "收到，我按你的反馈重新找替代方案。"
        if not alternatives:
            return intro + "不过当前商品库里没有找到足够接近的替代商品，可以放宽品牌、预算或类目。"
        names = "、".join(item.title[:16] for item in alternatives[:3])
        return intro + f"这几款更适合继续看：{names}。"

    async def _cached_response_text(self, session_id: str, message: str, products, constraints) -> RecommendationReply | None:
        key = self._recommendation_cache_key(session_id, message, products, constraints)
        cached = self.reply_cache.get(key)
        if not cached:
            observability.increment("recommendation_cache_misses")
            observability.add_current_step("recommendation_cache", {"hit": False})
            return None
        observability.increment("recommendation_cache_hits")
        observability.add_current_step(
            "recommendation_cache",
            {
                "hit": True,
                "source": cached.source,
                "text_chars": len(cached.text),
            },
        )
        return RecommendationReply(cached.text, cached.source)

    async def _response_text(self, session_id: str, message: str, products, constraints) -> RecommendationReply:
        fallback = RecommendationReply(self._fallback_response_text(message, products[:3], constraints), "fallback")
        llm_text = await self.llm.recommendation_reply(message, products, constraints, session_id=session_id)
        guarded = self.guard.validate(llm_text, products, constraints)
        if guarded:
            guarded = self.output_sanitizer.strip_internal_review_text(guarded)
            reply = RecommendationReply(guarded, "llm")
            self.reply_cache.set(self._recommendation_cache_key(session_id, message, products, constraints), guarded, "llm")
            return reply
        return fallback

    def _recommendation_cache_key(self, session_id: str, message: str, products, constraints) -> str:
        status = self.llm.status(session_id)
        return self.reply_cache.key(
            message=message,
            constraints=constraints,
            products=products,
            model_identity={
                "configured": status.configured,
                "provider": status.provider,
                "model": status.model,
            },
        )

    def _display_products_for_response(self, reply: RecommendationReply, products):
        if reply.source == "llm":
            return self._align_products_with_response(reply.text, products)
        return products[:3]

    def _align_products_with_response(self, text: str, products):
        if not products:
            return products
        compact_text = self._compact_for_match(text)
        mentioned: list[tuple[int, int, object]] = []
        for index, product in enumerate(products):
            position = self._product_mention_position(compact_text, product)
            if position is not None:
                mentioned.append((position, index, product))
        if not mentioned:
            return products
        mentioned.sort(key=lambda item: (item[0], item[1]))
        aligned = [product for _, _, product in mentioned]
        observability.add_current_step(
            "response_product_alignment",
            {
                "mode": "mentioned_products",
                "product_ids": [product.product_id for product in aligned],
            },
        )
        return aligned

    def _product_mention_position(self, compact_text: str, product) -> int | None:
        positions = [compact_text.find(alias) for alias in self._product_aliases(product) if alias and alias in compact_text]
        positions = [position for position in positions if position >= 0]
        return min(positions) if positions else None

    def _product_aliases(self, product) -> list[str]:
        aliases = [
            product.title,
            self._response_product_name(product),
        ]
        title = product.title
        model_patterns = [
            r"(?:Apple\s+)?iPhone\s*\d+\s*(?:Pro\s*Max|Pro|Plus|Max|Ultra)?",
            r"小米\s*\d+\s*(?:Max|Ultra|Pro)?",
            r"OPPO\s+(?:Reno|Find\s*N?|Find)\s*[A-Za-z0-9]+\s*(?:Pro|Ultra|Max)?",
            r"vivo\s+X\d+\s*(?:Ultra|Pro|Max)?",
            r"华为\s*(?:HUAWEI)?\s*Pura\s*\d+\s*(?:Pro|Ultra)?",
            r"HUAWEI\s*Pura\s*\d+\s*(?:Pro|Ultra)?",
        ]
        for pattern in model_patterns:
            aliases.extend(re.findall(pattern, title, re.I))
        if product.category != "数码电子":
            aliases.append(title[:24])
        normalized = []
        seen: set[str] = set()
        for alias in aliases:
            compact = self._compact_for_match(str(alias))
            if len(compact) < 4 or compact in seen:
                continue
            seen.add(compact)
            normalized.append(compact)
        return normalized

    def _compact_for_match(self, text: str) -> str:
        return re.sub(r"[\s，。！？,.!?*_/\\-]+", "", text.lower())

    def _fallback_response_text(self, message: str, products, constraints) -> str:
        names = "、".join(self._response_product_name(product) for product in products[:3])
        guard = "以下价格和商品信息都来自本地商品库。"
        if "对比" in message or "哪个" in message:
            return f"{guard} 我先把更匹配的几款放在前面：{names}。你可以点开商品卡片看详情，也可以继续说“对比前两款”。"
        if constraints.exclude_terms or constraints.exclude_brands:
            excluded = "、".join(dict.fromkeys(constraints.exclude_terms + constraints.exclude_brands))
            return f"{guard} 我已经排除了 {excluded} 相关商品，优先推荐：{names}。"
        return f"{guard} 根据你的需求，我优先推荐这几款：{names}。"

    def _response_product_name(self, product) -> str:
        title = product.title
        patterns = [
            r"(?:Apple\s+)?iPhone\s*\d+\s*(?:Pro\s*Max|Pro|Plus|Max|Ultra)?",
            r"小米\s*\d+\s*(?:Max|Ultra|Pro)?",
            r"OPPO\s+(?:Reno|Find\s*N?|Find)\s*[A-Za-z0-9]+\s*(?:Pro|Ultra|Max)?",
            r"vivo\s+X\d+\s*(?:Ultra|Pro|Max)?",
            r"华为\s*(?:HUAWEI)?\s*Pura\s*\d+\s*(?:Pro|Ultra)?",
            r"HUAWEI\s*Pura\s*\d+\s*(?:Pro|Ultra)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, title, re.I)
            if match:
                return re.sub(r"\s+", " ", match.group(0)).strip()
        return title if len(title) <= 28 else title[:28].rstrip() + "…"

    def _clarification_prompt(self, message: str, constraints, current_constraints) -> str | None:
        if self.intent.is_casual_no_preference(message) and constraints.category:
            return None
        if self.intent.has_specific_product_signal(message, constraints):
            return None
        compact = re.sub(r"[\s，。！？,.!?]", "", message)
        if not constraints.category and self.intent.is_vague_shopping(compact):
            if self.intent.is_gift(compact):
                return "可以，我先问清楚再推荐：是送给谁、什么场景或节日？对方更偏实用、数码、护肤美妆、运动户外还是零食礼盒？"
            return "可以，我先帮你缩小范围：这是自用还是送礼？预算大概多少？更想看数码、护肤美妆、服饰运动还是食品饮料？"
        if self.intent.has_enough_signal(current_constraints):
            return None
        if constraints.category == "数码电子" and self.intent.is_broad_subcategory(constraints.sub_category, ["手机", "智能手机"]):
            return "可以，我先帮你缩小范围：你更看重拍照、续航、游戏性能还是性价比？预算大概是多少？"
        if constraints.category == "美妆护肤" and not (constraints.include_terms or constraints.exclude_terms or constraints.max_price):
            return "可以。你的肤质是油皮、干皮还是敏感肌？预算大概多少？有没有要避开的成分或品牌？"
        if constraints.category == "服饰运动" and self.intent.is_broad_message(compact):
            return "可以。你更看重轻量、缓震、通勤百搭还是户外耐磨？预算大概是多少？"
        return None

    def _smalltalk_response(self, message: str) -> str | None:
        compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
        if compact in {"你好", "hello", "hi", "嗨"}:
            return "你好，我在。我可以像导购一样先问清需求，再基于本地商品库推荐、对比、反选和加购。你可以直接说“我想买手机”或“不要苹果，预算 7000”。"
        if "你" in compact and any(term in compact for term in ["什么模型", "哪个模型", "用的模型", "大模型"]):
            return "我是 ShopGuide 项目里的电商导购 Agent。模型大脑可以在左上角设置里切换为 DeepSeek 或其他 OpenAI-compatible 模型；商品检索、工具调用和防幻觉检查仍由本机后端统一控制。"
        if compact in {"你是谁", "你能做什么", "怎么用", "帮助", "help"}:
            return "我是这个项目里的电商导购 Agent。你可以和我正常聊天：先说模糊需求也行，我会主动追问；也可以说预算、偏好、不要的品牌/成分，我会只从商品库里找可验证的商品。还可以说“记住我以后护肤不要酒精”“1000元预算去三亚配一套”。"
        if compact in {"谢谢", "谢了", "thanks", "thankyou"}:
            return "不客气。你继续补充偏好、让我对比前两款，或者说把某一款加入购物车都可以。"
        return None

    def _profile_summary(self, profile) -> str:
        parts = []
        if profile.skin_type:
            parts.append(f"肤质是 {profile.skin_type}")
        if profile.budget_preferences:
            budgets = "、".join(f"{key}约{value:.0f}元" for key, value in profile.budget_preferences.items())
            parts.append(f"预算偏好：{budgets}")
        if profile.preferred_features:
            parts.append("偏好：" + "、".join(profile.preferred_features[:8]))
        if profile.excluded_brands:
            parts.append("排除品牌：" + "、".join(profile.excluded_brands))
        if profile.excluded_ingredients:
            parts.append("排除成分：" + "、".join(profile.excluded_ingredients))
        if profile.travel_scenario:
            parts.append("常见场景：" + "、".join(profile.travel_scenario))
        if not parts:
            return "你目前还没有保存长期偏好。可以说“记住我以后护肤品不要含酒精”或“以后买手机预算4000”。"
        return "这是我当前记住的偏好：" + "；".join(parts) + "。你可以说“清除我的偏好”重置。"

    def _plan_intro(self, plan, profile_updates: list[str]) -> str:
        if not plan:
            return "我暂时没能在商品库里配出完整方案，可以放宽预算或类目后再试。"
        prefix = ""
        if profile_updates:
            prefix = "我也顺手记住了这次场景偏好：" + "、".join(profile_updates[:3]) + "。"
        remaining_text = f"剩余预算约 {plan.remaining_budget:.0f} 元" if plan.remaining_budget >= 0 else f"超出预算约 {-plan.remaining_budget:.0f} 元"
        item_names = "、".join(item.product.title[:16] for item in plan.items[:4])
        return f"{prefix}我按预算和场景配了一套组合：{item_names}。总价约 {plan.total_price:.0f} 元，{remaining_text}。"

    async def _tokens(self, text: str) -> AsyncIterator[str]:
        for chunk in self._stream_units(text):
            await asyncio.sleep(0.012)
            yield chunk

    def _stream_units(self, text: str) -> list[str]:
        units: list[str] = []
        ascii_buffer: list[str] = []
        for char in text:
            if char.isascii() and (char.isalnum() or char in {"-", "_", "/", "."}):
                ascii_buffer.append(char)
                if len(ascii_buffer) >= 6:
                    units.append("".join(ascii_buffer))
                    ascii_buffer = []
                continue
            if ascii_buffer:
                units.append("".join(ascii_buffer))
                ascii_buffer = []
            units.append(char)
        if ascii_buffer:
            units.append("".join(ascii_buffer))
        return [unit for unit in units if unit]

    def _record_stream_event(self, event: dict) -> None:
        name = event.get("event")
        data = event.get("data")
        if name == "products" and isinstance(data, list):
            observability.increment("product_events")
            observability.add_current_step(
                "sse_products",
                {"count": len(data), "product_ids": [item.get("product_id") for item in data[:5] if isinstance(item, dict)]},
            )
        elif name == "cart" and isinstance(data, dict):
            observability.increment("cart_events")
            observability.add_current_step(
                "sse_cart",
                {"items": len(data.get("items") or []), "total_price": data.get("total_price")},
            )
        elif name == "compare" and isinstance(data, dict):
            observability.increment("compare_events")
            observability.add_current_step(
                "sse_compare",
                {"products": [item.get("product_id") for item in data.get("products", []) if isinstance(item, dict)]},
            )
        elif name == "plan" and isinstance(data, dict):
            observability.increment("plan_events")
            observability.add_current_step(
                "sse_plan",
                {
                    "title": data.get("title"),
                    "total_price": data.get("total_price"),
                    "items": len(data.get("items") or []),
                },
            )
        elif name == "profile" and isinstance(data, dict):
            observability.increment("profile_events")
            observability.add_current_step(
                "sse_profile",
                {
                    "has_budget": bool(data.get("budget_preferences")),
                    "excluded_brands": data.get("excluded_brands", []),
                    "excluded_ingredients": data.get("excluded_ingredients", []),
                },
            )
        elif name == "done" and isinstance(data, dict):
            observability.add_current_step("sse_done", {"ok": data.get("ok"), "needs_clarification": data.get("needs_clarification", False)})

    def _constraints_payload(self, constraints) -> dict:
        return {
            "category": constraints.category,
            "sub_category": constraints.sub_category,
            "max_price": constraints.max_price,
            "min_price": constraints.min_price,
            "include_terms": constraints.include_terms,
            "exclude_terms": constraints.exclude_terms,
            "exclude_brands": constraints.exclude_brands,
        }

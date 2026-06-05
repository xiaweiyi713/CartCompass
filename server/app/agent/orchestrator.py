from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, replace
from typing import AsyncIterator

from app.agent.after_sale_policy import AfterSalePolicyService
from app.agent.budget_planner import BudgetPlanner
from app.agent.conversation_mode import ConversationModeDecision, ConversationModeRouter
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
from app.agent.weather_service import KNOWN_LOCATIONS, WeatherService
from app.llm.gateway import LLMGateway
from app.llm.schemas import ConstraintInput, ConstraintOutput, ConversationPlanInput
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
        assistant_chunks: list[str] = []
        try:
            async for event in self._handle(request):
                if event["event"] == "token" and not first_token_seen:
                    first_token_seen = True
                    first_token_ms = (time.perf_counter() - started_at) * 1000
                    observability.record_latency("sse_first_token_latency_ms", first_token_ms)
                    observability.add_current_step("sse_first_token", {"latency_ms": round(first_token_ms, 2)})
                if event["event"] == "token" and isinstance(event.get("data"), str):
                    assistant_chunks.append(event["data"])
                if event["event"] == "done" and isinstance(event.get("data"), dict):
                    event = {**event, "data": {**event["data"], "trace_id": trace_id}}
                self._record_stream_event(event)
                yield f"event: {event['event']}\n"
                yield f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            self._record_transcript(request.session_id, request.message, "".join(assistant_chunks))
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
        profile_user_id = request.profile_user_id or request.session_id
        lowered = message.lower()

        if self.intent.is_profile_clear(message):
            profile = self.profiles.clear(profile_user_id)
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
            profile = self.profiles.get(profile_user_id)
            observability.increment("profile_views")
            observability.add_current_step("profile", {"action": "view", "profile": profile.model_dump()})
            async for token in self._tokens(self._profile_summary(profile)):
                yield {"event": "token", "data": token}
            yield {"event": "profile", "data": profile.model_dump()}
            yield {"event": "done", "data": {"ok": True}}
            return

        if self.intent.is_profile_remember(message):
            profile, updates = self.profiles.remember_from_message(profile_user_id, message)
            observability.increment("profile_updates")
            observability.add_current_step("profile", {"action": "remember", "updates": updates, "profile": profile.model_dump()})
            if updates:
                prefix = "我已把这条长期偏好保存为：" if self.intent.is_implicit_profile_statement(message) else "我已经记住："
                text = prefix + "、".join(updates) + "。之后相关类目的推荐会自动带上这些偏好。"
            else:
                text = "这句话里我没有识别到可长期保存的预算、肤质、品牌或成分偏好。"
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

        if session.pending_checkout and self._is_checkout_followup(message):
            observability.increment("checkout_confirmation_turns")
            observability.add_current_step("intent", {"name": "checkout_confirmation", "pending": session.pending_checkout})
            async for event in self._handle_cart(request.session_id, message, session.last_product_ids):
                yield event
            return

        weather_followup_location = self._weather_followup_location(message, session)
        if weather_followup_location:
            observability.increment("weather_turns")
            observability.add_current_step(
                "conversation_mode",
                {
                    "mode": "weather_query",
                    "intent_level": 0,
                    "need_rag": False,
                    "need_product_cards": False,
                    "need_tool_call": False,
                    "reason": "weather_followup_location",
                    "location": weather_followup_location,
                },
            )
            async for event in self._handle_weather(message, location_override=weather_followup_location):
                yield event
            return

        if self._is_sleep_environment_followup(message, session):
            observability.increment("sleep_environment_followup_intents")
            observability.add_current_step(
                "conversation_mode",
                {
                    "mode": "shopping_assist",
                    "intent_level": 3,
                    "need_rag": True,
                    "need_product_cards": True,
                    "reason": "sleep_environment_non_medical_followup",
                },
            )
            async for event in self._handle_sleep_environment_shopping(request.session_id, message, session):
                yield event
            return

        if self._is_campus_starter_intent(message):
            observability.increment("campus_starter_intents")
            observability.add_current_step(
                "conversation_mode",
                {
                    "mode": "shopping_assist",
                    "intent_level": 3,
                    "need_rag": True,
                    "need_product_cards": True,
                    "reason": "campus_starter_kit",
                },
            )
            async for event in self._handle_campus_starter_kit(request.session_id, message, session):
                yield event
            return

        if self._is_non_food_gift_intent(message):
            observability.increment("non_food_gift_intents")
            observability.add_current_step(
                "conversation_mode",
                {
                    "mode": "shopping_assist",
                    "intent_level": 3,
                    "need_rag": True,
                    "need_product_cards": True,
                    "reason": "non_food_gift_context_reset",
                },
            )
            async for event in self._handle_non_food_gift(request.session_id, message, session):
                yield event
            return

        mode, plan = await self._route_mode(request.session_id, message, session)
        observability.add_current_step(
            "conversation_mode",
            {
                "mode": mode.mode,
                "intent_level": mode.shopping_intent_level,
                "need_rag": mode.need_rag,
                "need_product_cards": mode.need_product_cards,
                "need_tool_call": mode.need_tool_call,
                "reason": mode.reason,
                "planner": plan.intent if plan else None,
            },
        )
        plan_reply = plan.reply.strip() if plan and plan.reply else ""
        if self._planned(plan, "after_sale") or self.intent.is_after_sale(message):
            observability.increment("after_sale_policy_intents")
            observability.add_current_step("intent", {"name": "after_sale_policy", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_after_sale_policy(message, session.last_product_ids):
                yield event
            return
        if self._planned(plan, "feedback") or self.intent.is_feedback(message, session.last_product_ids):
            observability.increment("feedback_intents")
            observability.add_current_step("intent", {"name": "feedback", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_feedback(request.session_id, profile_user_id, message, session.last_product_ids):
                yield event
            return
        if self._planned(plan, "product_qa") or self.intent.is_product_qa(message, session.last_product_ids):
            observability.increment("product_qa_intents")
            observability.add_current_step("intent", {"name": "product_qa", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_product_qa(message, session.last_product_ids):
                yield event
            return
        if mode.mode == "general_chat":
            observability.increment("general_chat_turns")
            async for event in self._handle_general_chat(request.session_id, message, reply=plan_reply or None):
                yield event
            return
        if mode.mode == "weather_query":
            observability.increment("weather_turns")
            async for event in self._handle_weather(message):
                yield event
            return
        if mode.mode == "product_knowledge":
            observability.increment("product_knowledge_turns")
            async for event in self._handle_product_knowledge(request.session_id, message, reply=plan_reply or None):
                yield event
            return
        if mode.mode == "weak_purchase_intent":
            observability.increment("weak_purchase_intents")
            text = self.guard.sanitize_chat(plan_reply) or self._weak_purchase_prompt(message)
            if self._is_sleep_lifestyle_message(message):
                session.pending_lifestyle_intent = "sleep_environment"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": {"ok": True, "mode": "weak_purchase_intent", "needs_clarification": True}}
            return

        if self._planned(plan, "compare") or self.intent.is_compare(lowered):
            observability.increment("compare_intents")
            observability.add_current_step("intent", {"name": "compare", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_compare(message, session.last_product_ids):
                yield event
            return

        if self._planned(plan, "cart") or self.intent.is_cart(lowered):
            observability.increment("cart_intents")
            observability.add_current_step("intent", {"name": "cart", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_cart(request.session_id, message, session.last_product_ids):
                yield event
            return

        if self._planned(plan, "feedback") or self.intent.is_feedback(message, session.last_product_ids):
            observability.increment("feedback_intents")
            observability.add_current_step("intent", {"name": "feedback", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_feedback(request.session_id, profile_user_id, message, session.last_product_ids):
                yield event
            return

        if self.intent.is_more_results(message, session.last_product_ids):
            observability.increment("more_results_intents")
            observability.add_current_step("intent", {"name": "more_results", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_more_results(request.session_id, message):
                yield event
            return

        if self._planned(plan, "after_sale") or self.intent.is_after_sale(message):
            observability.increment("after_sale_policy_intents")
            observability.add_current_step("intent", {"name": "after_sale_policy", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_after_sale_policy(message, session.last_product_ids):
                yield event
            return

        if self._planned(plan, "product_qa") or self.intent.is_product_qa(message, session.last_product_ids):
            observability.increment("product_qa_intents")
            observability.add_current_step("intent", {"name": "product_qa", "last_product_ids": session.last_product_ids[:5]})
            async for event in self._handle_product_qa(message, session.last_product_ids):
                yield event
            return

        if self.planner.can_plan(message):
            observability.increment("budget_plan_intents")
            observability.add_current_step("intent", {"name": "budget_plan"})
            profile, profile_updates = self.profiles.remember_scenario_from_message(profile_user_id, message)
            plan = await asyncio.to_thread(self.planner.build, profile_user_id, message)
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
            bundle = await asyncio.to_thread(
                self.travel_planner.build, message, travel_plan, weather_context=weather_context
            )
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
        constraints = self.profiles.apply_to_constraints(profile_user_id, constraints, message=message)
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

        had_pending_clarification = bool(session.pending_clarification)
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
        # Make the UI feel responsive: product retrieval is already grounded and
        # safe, so send cards immediately instead of waiting for the LLM wording
        # pass to finish.
        display_count = 3 if had_pending_clarification else 5
        early_display_products = products[:display_count]
        yield {"event": "products", "data": [product.model_dump() for product in early_display_products]}
        fast_reply = RecommendationReply(
            self._fallback_response_text(message, early_display_products[:3], constraints, include_exclusion=True),
            "fast",
        )
        async for token in self._tokens(fast_reply.text):
            yield {"event": "token", "data": token}
        session.last_product_ids = [product.product_id for product in early_display_products]
        yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
        return
        reply = await self._cached_response_text(request.session_id, message, products, constraints)
        has_streamed_tokens = False
        if not reply:
            # The deterministic prefix already acknowledges any exclusion, so the
            # streaming fallback must not repeat it (the non-streaming path keeps it).
            fallback = RecommendationReply(
                self._fallback_response_text(message, products[:3], constraints, include_exclusion=False),
                "fallback",
            )
            streamed_chunks: list[str] = []
            pending = ""
            answer_started = False
            answer_emitted = False
            stream_blocked = False
            # Emit the grounded prefix immediately (deterministic), so first-token
            # latency tracks retrieval time rather than the model's TTFT, and the
            # negative-constraint acknowledgement ("已排除…") is guaranteed even when
            # the LLM rephrases the answer without it. The LLM elaboration then
            # streams after this safe prefix.
            grounded_prefix = self._grounded_prefix(constraints)
            async for token in self._tokens(grounded_prefix):
                has_streamed_tokens = True
                yield {"event": "token", "data": token}
            streamed_chunks.append(grounded_prefix)
            # Grounded answer packet construction:
            # - `message` is the user's current turn.
            # - `products` are already database-backed cards selected by RAG.
            # - `constraints` are the parsed budget/category/exclusion facts.
            # The LLM only receives that packet and may polish wording; it never
            # chooses product IDs, prices, SKU, stock, or source URLs. Each pending
            # segment is sanitized before flush, then the complete text is checked
            # again below before it can be cached as an LLM answer.
            async for chunk in self.llm.stream_recommendation_reply(message, products, constraints, session_id=request.session_id):
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
                # Segment-level guard: do not stream a chunk until it is safe
                # against the product packet accumulated so far. This is the main
                # defense against visible hallucinations in SSE; unsafe chunks are
                # blocked before the user can see them.
                if not self.output_sanitizer.is_safe_stream_segment("".join(streamed_chunks), pending, products, constraints):
                    stream_blocked = True
                    break
                streamed_chunks.append(pending)
                has_streamed_tokens = True
                answer_emitted = True
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
                    answer_emitted = True
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
            elif not answer_emitted:
                # Prefix emitted but the model returned nothing usable → stream the
                # deterministic recommendation so the user still gets a real answer.
                reply = fallback
                async for token in self._tokens(fallback.text):
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
        if reply.source == "fallback" and self.llm.status(request.session_id).configured:
            yield {"event": "fallback", "data": notice("model_unavailable").model_dump()}
        yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}

    async def _route_mode(self, session_id: str, message: str, session):
        """LLM planner first (natural, context-aware routing); deterministic rule
        router as fallback when the model is unconfigured or returns invalid output."""
        rule_mode = self.mode_router.route(
            message,
            has_last_products=bool(session.last_product_ids),
            has_pending_clarification=bool(session.pending_clarification),
            has_active_shopping_context=bool(session.constraints.category),
        )
        if not self.llm.status(session_id).configured:
            return rule_mode, None
        # Latency fast-path: skip the planner LLM call for high-confidence explicit
        # intents (cart/checkout, explicit compare/qa/feedback/after-sale, or a
        # specific "recommend + category + price/sub/preference" request). The
        # planner is reserved for ambiguous turns where chat↔shop disambiguation
        # actually matters — keeping first-token latency low on explicit commands.
        if self._high_confidence_route(message, rule_mode, session):
            observability.add_current_step("planner_fast_path", {"mode": rule_mode.mode, "reason": "high_confidence_rule"})
            return rule_mode, None
        try:
            plan = await asyncio.wait_for(
                self.llm.plan_turn(
                    ConversationPlanInput(
                        user_message=message,
                        history=session.recent_transcript(8),
                        has_last_products=bool(session.last_product_ids),
                        has_active_category=bool(session.constraints.category),
                        cart_item_count=len(self.cart.state(session_id).items),
                    ),
                    session_id=session_id,
                ),
                timeout=1.5,
            )
        except asyncio.TimeoutError:
            observability.add_current_step("planner_fast_path", {"mode": rule_mode.mode, "reason": "planner_timeout"})
            return rule_mode, None
        if not plan:
            return rule_mode, None
        return self._plan_to_mode(plan, rule_mode), plan

    def _high_confidence_route(self, message: str, rule_mode: ConversationModeDecision, session) -> bool:
        lowered = message.lower()
        last = session.last_product_ids
        if rule_mode.mode == "transaction":
            return True
        if rule_mode.mode in {"weather_query", "travel_weather_planning"}:
            return True
        if rule_mode.mode == "shopping_assist":
            return True
        if self.intent.is_compare(lowered) or self.intent.is_cart(lowered):
            return True
        if self.intent.is_feedback(message, last) or self.intent.is_after_sale(message) or self.intent.is_product_qa(message, last):
            return True
        # Specific (not vague) recommendation request: category plus at least one
        # concrete constraint. Broad asks like "推荐手机" still go to the planner.
        if rule_mode.mode == "shopping_assist":
            parsed = self.parser.parse(message)
            if parsed.category and (parsed.max_price or parsed.min_price or parsed.sub_category or parsed.include_terms):
                return True
        return False

    def _plan_to_mode(self, plan, fallback: ConversationModeDecision) -> ConversationModeDecision:
        if plan.intent == "unknown":
            return fallback
        mapping = {
            "smalltalk": "general_chat",
            "product_knowledge": "product_knowledge",
            "weather": "weather_query",
            "clarify": "weak_purchase_intent",
            "cart": "transaction",
        }
        mode_name = mapping.get(plan.intent, "shopping_assist")
        return ConversationModeDecision(
            mode=mode_name,
            shopping_intent_level=max(0, min(4, plan.shopping_intent_level)),
            need_rag=mode_name == "shopping_assist",
            need_product_cards=mode_name == "shopping_assist" and plan.shopping_intent_level >= 3,
            need_tool_call=mode_name == "transaction",
            reason=f"llm_planner:{plan.intent}",
        )

    @staticmethod
    def _planned(plan, intent_name: str) -> bool:
        return plan is not None and plan.intent == intent_name

    def _record_transcript(self, session_id: str, user_message: str, assistant_text: str) -> None:
        session = self.sessions.get(session_id)
        session.add_turn("user", user_message)
        session.add_turn("assistant", assistant_text)

    def _base_constraints_for_message(self, session, parsed_constraints):
        base_constraints = session.pending_constraints or session.constraints
        if parsed_constraints.category and base_constraints.category and parsed_constraints.category != base_constraints.category:
            return parsed_constraints
        if parsed_constraints.category and parsed_constraints.sub_category:
            return parsed_constraints
        return base_constraints

    async def _search_products(self, query: str, constraints: SearchConstraints, limit: int = 5):
        # RAG entry point for the Agent. The orchestrator owns dialog state and
        # tool routing, but the actual retrieval contract lives in
        # ProductRepository: SQL hard filters -> BM25 exact-term scoring ->
        # pluggable vector store (Chroma/text embedding/hash fallback) ->
        # structured/trust rerank. Keeping this as a thread hop prevents SQLite
        # and vector scoring from blocking the async SSE stream.
        return await asyncio.to_thread(self.products.search, query, constraints, limit)

    async def _refine_constraints_with_llm(self, session_id: str, message: str, session, parsed_constraints) -> object:
        if not self.llm.status(session_id).configured:
            return parsed_constraints
        # Latency fast-path: when deterministic parsing already pinned a category,
        # skip the LLM constraint-fill call (the common explicit-request case).
        # Only spend an LLM round-trip when the rule parser came back empty.
        if parsed_constraints.category:
            return parsed_constraints
        try:
            output = await asyncio.wait_for(
                self.llm.parse_constraints(
                    ConstraintInput(
                        user_message=message,
                        current_constraints=self._constraints_payload(session.pending_constraints or session.constraints),
                    ),
                    session_id=session_id,
                ),
                timeout=1.2,
            )
        except asyncio.TimeoutError:
            observability.add_current_step("constraint_parser", {"llm_refine": "timeout"})
            return parsed_constraints
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

    async def _handle_general_chat(self, session_id: str, message: str, reply: str | None = None) -> AsyncIterator[dict]:
        text = reply
        if not text:
            fallback = self._general_chat_fallback(message)
            compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
            if any(term in compact for term in ["你是谁", "你是啥", "介绍一下", "shopguide"]):
                text = fallback
            else:
                try:
                    text = await asyncio.wait_for(
                        self.llm.general_chat(message, mode="general_chat", session_id=session_id),
                        timeout=1.5,
                    )
                except asyncio.TimeoutError:
                    observability.add_current_step("general_chat", {"llm": "timeout"})
                    text = fallback
        text = self.guard.sanitize_chat(text)
        if not text:
            text = self._general_chat_fallback(message)
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "done", "data": {"ok": True, "mode": "general_chat"}}

    async def _handle_product_knowledge(self, session_id: str, message: str, reply: str | None = None) -> AsyncIterator[dict]:
        if self._is_health_claim_message(message):
            self.sessions.get(session_id).pending_lifestyle_intent = "sleep_environment"
            text = self._product_knowledge_fallback(message)
        else:
            text = reply or await self.llm.general_chat(message, mode="product_knowledge", session_id=session_id)
        text = self.guard.sanitize_chat(text)
        if not text:
            text = self._product_knowledge_fallback(message)
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "done", "data": {"ok": True, "mode": "product_knowledge"}}

    async def _handle_weather(self, message: str, location_override: str | None = None) -> AsyncIterator[dict]:
        location = location_override or self.intent.weather_location(message)
        context = None
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
        if context:
            yield {"event": "weather", "data": context.model_dump()}
        yield {"event": "done", "data": {"ok": True, "mode": "weather_query"}}

    async def _handle_sleep_environment_shopping(self, session_id: str, message: str, session) -> AsyncIterator[dict]:
        parsed = self.parser.parse(message)
        constraints = SearchConstraints(
            category="数码电子",
            sub_category="耳机",
            max_price=parsed.max_price,
            min_price=parsed.min_price,
            include_terms=list(dict.fromkeys(parsed.include_terms + ["降噪", "通勤"])),
            exclude_terms=parsed.exclude_terms,
            exclude_brands=parsed.exclude_brands,
        )
        products = await self._search_products(
            f"{message} 改善卧室睡眠环境 非医疗 降噪 安静 蓝牙耳机",
            constraints,
            limit=5,
        )
        session.pending_lifestyle_intent = None
        session.pending_constraints = None
        session.pending_clarification = None
        session.constraints = constraints
        session.last_product_ids = [product.product_id for product in products[:5]]

        if not products:
            text = "我理解你是想改善卧室睡眠环境。当前商品库没有精确的遮光、寝具或降噪候选，可以补充预算或换成“降噪耳机/眼罩/床品”等更具体目标再试。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "fallback", "data": empty_recommendation_notice(text, constraints).model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
            return

        names = "、".join(self._response_product_name(product) for product in products[:3])
        text = (
            "我按非医疗的卧室环境改善来筛选，不推荐药品，也不会承诺治疗失眠。"
            f"本地商品库里更贴近的是降噪/安静场景候选：{names}。"
            "如果你有预算，我可以继续按价格区间缩小范围。"
        )
        yield {"event": "products", "data": [product.model_dump() for product in products[:5]]}
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}

    async def _handle_campus_starter_kit(self, session_id: str, message: str, session) -> AsyncIterator[dict]:
        parsed = self.parser.parse(message)
        slots = [
            ("随身收纳", "服饰运动", "背包", "校园 通勤 双肩包 电脑包 轻量 收纳", "装电脑、书本和日常随身物品"),
            ("电子补电", "数码电子", "充电设备", "学生 充电宝 快充 数据线 便携", "上课、社团和外出时给手机电脑补电"),
            ("舒适步行", "服饰运动", "运动鞋", "校园 通勤 缓震 跑鞋 日常步行", "校园通勤和军训外的日常步行更舒服"),
            ("学习补给", "食品饮料", "咖啡", "学习 提神 速溶 咖啡 便携", "早八或复习时做便携提神补给"),
        ]
        products = []
        seen: set[str] = set()
        for need, category, sub_category, query, reason in slots:
            constraints = SearchConstraints(
                category=category,
                sub_category=sub_category,
                max_price=parsed.max_price,
                min_price=parsed.min_price,
                include_terms=[],
                exclude_terms=list(parsed.exclude_terms),
                exclude_brands=list(parsed.exclude_brands),
            )
            matches = await self._search_products(query, constraints, limit=3)
            selected_matches = sorted(matches, key=lambda item: item.base_price) if parsed.max_price is None else matches
            for product in selected_matches:
                if product.product_id in seen:
                    continue
                seen.add(product.product_id)
                product.reason = f"{product.reason}；用于{need}：{reason}" if product.reason else f"用于{need}：{reason}"
                products.append(product)
                break

        session.pending_lifestyle_intent = None
        session.pending_constraints = None
        session.pending_clarification = None
        session.constraints = SearchConstraints()
        session.last_product_ids = [product.product_id for product in products[:5]]

        if not products:
            constraints = SearchConstraints(include_terms=["上大学", "开学", "校园清单"])
            text = "我识别到这是入学/校园生活清单需求，但当前商品库没有筛到可用候选。可以补充预算或指定类目，比如背包、充电宝、鞋、床品后再试。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "fallback", "data": empty_recommendation_notice(text, constraints).model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
            return

        category_names = "、".join(self._response_product_name(product) for product in products[:4])
        budget_hint = "如果你给总预算，我可以继续把这套清单压到预算内。" if parsed.max_price is None else "我已按你提到的预算范围做了价格过滤。"
        text = (
            "这不是商品库没有，而是入学/校园生活属于清单型购买需求。"
            "我按本地商品库从随身收纳、电子补电、舒适步行和学习补给各挑代表商品："
            f"{category_names}。{budget_hint}"
        )
        yield {"event": "products", "data": [product.model_dump() for product in products[:5]]}
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}

    def _is_campus_starter_intent(self, message: str) -> bool:
        compact = re.sub(r"[\s，。！？,.!?；;：:、]+", "", message.lower())
        campus_terms = ["上大学", "大学", "大学生", "开学", "入学", "返校", "校园", "宿舍", "寝室", "军训"]
        buy_terms = ["买什么", "买点什么", "要买", "需要买", "需要准备", "准备什么", "带什么", "清单", "推荐", "配一套", "应该买"]
        return any(term in compact for term in campus_terms) and any(term in compact for term in buy_terms)

    async def _handle_non_food_gift(self, session_id: str, message: str, session) -> AsyncIterator[dict]:
        parsed = self.parser.parse(message)
        slots = [
            ("实用数码", "数码电子", "充电设备", "送人 礼物 便携 快充 充电宝 实用", "不挑口味，日常使用频率高"),
            ("音频娱乐", "数码电子", "耳机", "送人 礼物 蓝牙耳机 降噪 音质", "适合通勤、学习或娱乐"),
            ("通勤收纳", "服饰运动", "背包", "送人 礼物 通勤 双肩包 轻量 收纳", "实用但不像食品一样有口味限制"),
            ("日常护理", "美妆护肤", "防晒", "送人 礼物 防晒 日常 通勤 护理", "偏生活实用型，适合日常防护"),
        ]
        products = []
        seen: set[str] = set()
        for need, category, sub_category, query, reason in slots:
            constraints = SearchConstraints(
                category=category,
                sub_category=sub_category,
                max_price=parsed.max_price,
                min_price=parsed.min_price,
                include_terms=[],
                exclude_terms=list(parsed.exclude_terms),
                exclude_brands=list(parsed.exclude_brands),
            )
            matches = await self._search_products(query, constraints, limit=4)
            selected_matches = sorted(matches, key=lambda item: item.base_price) if parsed.max_price is None else matches
            for product in selected_matches:
                if product.product_id in seen or product.category == "食品饮料":
                    continue
                seen.add(product.product_id)
                product.reason = f"{product.reason}；用于{need}：{reason}" if product.reason else f"用于{need}：{reason}"
                products.append(product)
                break

        session.pending_lifestyle_intent = None
        session.pending_constraints = None
        session.pending_clarification = None
        session.constraints = SearchConstraints()
        session.last_product_ids = [product.product_id for product in products[:5]]

        if not products:
            constraints = SearchConstraints(exclude_terms=["食品", "食物", "零食", "饮料"])
            text = "我已理解为非食品礼物需求，并且不会沿用上一轮食品推荐。当前商品库没有筛到合适的非食品礼物，可以补充预算、性别/关系或使用场景后再试。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "fallback", "data": empty_recommendation_notice(text, constraints).model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
            return

        names = "、".join(self._response_product_name(product) for product in products[:4])
        text = (
            "我已理解为非食品礼物需求，并且重置了上一轮食品饮料上下文。"
            f"这次只从非食品类目里挑：{names}。"
            "如果你补充预算、送给谁和场景，我可以继续缩小到更合适的 2-3 款。"
        )
        yield {"event": "products", "data": [product.model_dump() for product in products[:5]]}
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}

    def _is_non_food_gift_intent(self, message: str) -> bool:
        compact = re.sub(r"[\s，。！？,.!?；;：:、]+", "", message.lower())
        gift_terms = ["礼物", "送人", "送别人", "送朋友", "送女生", "送男生", "生日", "纪念日"]
        non_food_terms = [
            "不是食物",
            "不是食品",
            "不要食物",
            "不要食品",
            "非食物",
            "非食品",
            "别是食物",
            "别是食品",
            "不想要食物",
            "不想要食品",
        ]
        return any(term in compact for term in gift_terms) and any(term in compact for term in non_food_terms)

    def _weather_followup_location(self, message: str, session) -> str | None:
        if not self._has_recent_weather_context(session):
            return None
        compact = self.intent.compact(message)
        if not compact or self.intent.is_weather(message):
            return None
        if any(term in compact for term in ["推荐", "买", "加购", "购物车", "对比", "比较", "多少钱", "价格", "预算"]):
            return None
        candidate = compact.strip("呢吗呀啊了的")
        candidate = re.sub(r"^(那|那么|再看|看看|查查|问下|问一下)", "", candidate)
        candidate = candidate.strip("呢吗呀啊了的")
        if not candidate or len(candidate) > 12:
            return None
        for key in KNOWN_LOCATIONS:
            if key in candidate or candidate in key:
                return candidate
        return None

    def _has_recent_weather_context(self, session) -> bool:
        for turn in reversed(session.recent_transcript(4)):
            content = str(turn.get("content") or "")
            if turn.get("role") == "assistant" and "当前天气" in content and "数据源" in content:
                return True
            if turn.get("role") == "user" and self.intent.is_weather(content):
                return True
        return False

    def _general_chat_fallback(self, message: str) -> str:
        compact = re.sub(r"[\s，。！？,.!?]", "", message)
        lower = compact.lower()
        if any(term in lower for term in ["你是谁", "你是啥", "介绍一下", "shopguide"]):
            return "我是 ShopGuide，一个电商导购 Agent。可以正常聊天；当你给出预算、类目、偏好或排除条件时，我会只基于商品库推荐可验证的商品。"
        if any(term in compact for term in ["烦", "累", "压力", "焦虑", "心情不好"]):
            return (
                "听起来你现在状态不太舒服。可以先把问题拆小一点：休息、吃饭、运动或整理环境，选一个最容易做的。"
                "如果后面你确实想找能改善生活状态的东西，再告诉我预算和使用场景，我会再进入导购模式。"
            )
        return "我可以正常聊天，也可以在你有明确购买、比较、预算或加购需求时切换到导购模式。你可以继续说。"

    def _product_knowledge_fallback(self, message: str) -> str:
        compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
        if self._is_health_claim_message(message):
            return (
                "睡眠问题不能靠普通商品保证治疗或治愈，我不能把商品当作医疗方案推荐。"
                "如果失眠持续、明显影响白天状态，建议先咨询医生或专业人士。"
                "如果你只是想改善睡眠环境，我可以在你确认预算后，按遮光、降噪、舒适寝具等非医疗场景帮你筛选。"
            )
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

    def _is_health_claim_message(self, message: str) -> bool:
        compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
        health_targets = ["失眠", "睡不着", "睡眠障碍", "焦虑", "抑郁", "膝盖疼", "疼痛"]
        claim_terms = ["治", "治疗", "治好", "治愈", "药", "处方", "保证"]
        return any(target in compact for target in health_targets) and any(term in compact for term in claim_terms)

    def _is_sleep_lifestyle_message(self, message: str) -> bool:
        compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
        return any(term in compact for term in ["睡眠", "失眠", "睡不着", "睡不好", "卧室环境", "睡眠环境"])

    def _is_sleep_environment_followup(self, message: str, session) -> bool:
        compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
        if not compact:
            return False
        environment_terms = [
            "改善睡眠环境",
            "睡眠环境",
            "卧室环境",
            "房间环境",
            "环境",
            "安静",
            "降噪",
            "遮光",
            "眼罩",
            "耳塞",
            "寝具",
            "枕头",
        ]
        if session.pending_lifestyle_intent == "sleep_environment" and any(term in compact for term in environment_terms):
            return True
        recent = " ".join(str(turn.get("content") or "") for turn in session.recent_transcript(4))
        recent_sleep_context = any(term in recent for term in ["睡眠", "失眠", "睡不着", "改善睡眠环境", "卧室环境"])
        if recent_sleep_context and any(term in compact for term in ["卧室环境", "睡眠环境", "降噪", "遮光", "眼罩"]):
            return True
        return False

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
        session = self.sessions.get(session_id)
        pending_checkout = session.pending_checkout or None
        if pending_checkout:
            async for event in self._handle_checkout_confirmation(session_id, message, pending_checkout):
                yield event
            return

        target_id = self.intent.target_product_id(message, last_product_ids)
        if any(word in message for word in ["结算", "付款", "支付", "下单"]):
            state = self.cart.state(session_id)
            if state.items:
                address = self._extract_checkout_address(message)
                if address:
                    session.pending_checkout = {"step": "confirm", "address": address}
                    text = (
                        f"收货地址已记录：{address}\n"
                        f"{self._cart_order_summary(state)}\n"
                        "请回复“确认下单”完成模拟下单，或回复“取消下单”。本项目不会产生真实支付和物流。"
                    )
                else:
                    session.pending_checkout = {"step": "address"}
                    text = (
                        "下单前需要先确认收货地址。\n"
                        f"{self._cart_order_summary(state)}\n"
                        "请直接回复收货地址，例如“北京市朝阳区 Demo 路 1 号”。"
                    )
            else:
                session.pending_checkout = None
                text = "购物车还是空的。先让我推荐商品并加入购物车后，再进入沙箱结算。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "cart", "data": state.model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "transaction"}}
            return
        if "清空" in message:
            session.pending_checkout = None
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
        product = self.products.get(target_id)
        sku_id = self._sku_id_from_message(product, message) if product else None
        if any(word in message for word in ["删", "移除", "不要了"]):
            state = self.cart.remove(session_id, target_id, sku_id=sku_id)
            text = "已从购物车移除这款商品。"
        elif any(word in message for word in ["改成", "数量", "设为"]):
            state = self.cart.update(session_id, target_id, quantity, sku_id=sku_id)
            text = f"已把这款商品数量改为 {quantity}。"
        else:
            state = self.cart.add(session_id, target_id, quantity, sku_id=sku_id)
            sku_text = self._sku_label(product, sku_id) if product and sku_id else ""
            suffix = f"（{sku_text}）" if sku_text else ""
            text = f"已加入购物车{suffix}，数量 {quantity}。"

        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "cart", "data": state.model_dump()}
        yield {"event": "done", "data": {"ok": True, "mode": "transaction"}}

    async def _handle_checkout_confirmation(self, session_id: str, message: str, pending_checkout: dict) -> AsyncIterator[dict]:
        session = self.sessions.get(session_id)
        state = self.cart.state(session_id)
        compact = re.sub(r"[\s，。！？,.!?；;：:、]+", "", message.lower())

        if any(term in compact for term in ["取消下单", "取消结算", "先不下单", "不下单", "取消"]):
            session.pending_checkout = None
            text = "已取消本次下单确认，购物车内容仍然保留。你可以继续调整商品或重新说“下单”。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "cart", "data": state.model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "transaction", "checkout_cancelled": True}}
            return

        if not state.items:
            session.pending_checkout = None
            text = "购物车已经为空，无法继续下单。先加入商品后再说“下单”。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "cart", "data": state.model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "transaction"}}
            return

        address = self._extract_checkout_address(message)
        if address:
            session.pending_checkout = {"step": "confirm", "address": address}
            text = (
                f"收货地址已更新：{address}\n"
                f"{self._cart_order_summary(state)}\n"
                "请回复“确认下单”完成模拟下单，或回复“取消下单”。"
            )
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "cart", "data": state.model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "transaction", "needs_confirmation": True}}
            return

        step = str(pending_checkout.get("step") or "address")
        saved_address = str(pending_checkout.get("address") or "").strip()
        if step == "confirm" and saved_address and self._is_checkout_confirmation(message):
            order = self.cart.checkout(session_id, saved_address)
            session.pending_checkout = None
            new_state = self.cart.state(session_id)
            text = (
                "模拟下单已完成。\n"
                f"订单号：{order.order_id}\n"
                f"收货地址：{order.address}\n"
                f"订单金额：¥{order.total_price:.0f}\n"
                "订单状态：已创建，支付状态为演示未支付；本项目不会产生真实扣款或物流。"
            )
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "order", "data": order.model_dump()}
            yield {"event": "cart", "data": new_state.model_dump()}
            yield {
                "event": "done",
                "data": {
                    "ok": True,
                    "mode": "transaction",
                    "checkout_completed": True,
                    "order_id": order.order_id,
                },
            }
            return

        if step == "confirm" and saved_address:
            text = (
                f"我已经记录收货地址：{saved_address}\n"
                f"{self._cart_order_summary(state)}\n"
                "如果信息无误，请回复“确认下单”；如果要改地址，直接发新的收货地址；也可以回复“取消下单”。"
            )
        else:
            session.pending_checkout = {"step": "address"}
            text = (
                "我还需要收货地址才能继续下单。\n"
                f"{self._cart_order_summary(state)}\n"
                "请直接回复收货地址，例如“北京市朝阳区 Demo 路 1 号”。"
            )
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "cart", "data": state.model_dump()}
        yield {"event": "done", "data": {"ok": True, "mode": "transaction", "needs_confirmation": True}}

    async def _handle_feedback(
        self,
        session_id: str,
        profile_user_id: str,
        message: str,
        last_product_ids: list[str],
    ) -> AsyncIterator[dict]:
        target_id = self.intent.target_product_id(message, last_product_ids)
        product = self.products.get(target_id) if target_id else None
        if not product:
            async for token in self._tokens("我还不知道你反馈的是哪款商品，可以先让我推荐几款，再说“第一款太贵了”或“换个品牌”。"):
                yield {"event": "token", "data": token}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
            return

        feedback = self.intent.feedback_type(message)
        profile = self.profiles.record_feedback(profile_user_id, product.product_id, feedback, message[:80])
        if feedback == "like":
            text = f"收到，我会把你喜欢 {product.brand} 这类商品记到反馈里。你可以继续让我对比、加购，或者说“找更便宜的”。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "profile", "data": profile.model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
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
        yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist", "feedback": feedback}}

    async def _handle_more_results(self, session_id: str, message: str) -> AsyncIterator[dict]:
        session = self.sessions.get(session_id)
        constraints = self._continued_constraints(session)
        products = await self._search_products(self._continued_query(message, constraints), constraints, limit=12)
        products = self._business_rank_products(message, constraints, products)[:5]
        session.pending_constraints = None
        session.pending_clarification = None
        session.constraints = replace(constraints, exclude_product_ids=[])
        session.last_product_ids = [product.product_id for product in products]
        if not products:
            text = "我按上一轮条件继续找了一遍，但当前商品库里没有更多合适候选。可以放宽预算、品牌或换一个侧重点。"
            async for token in self._tokens(text):
                yield {"event": "token", "data": token}
            yield {"event": "fallback", "data": empty_recommendation_notice(text, constraints).model_dump()}
            yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}
            return

        names = "、".join(self._response_product_name(product) for product in products[:3])
        text = f"可以，我按上一轮条件继续找，并避开刚刚展示过的款式。这几款也可以看：{names}。"
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "products", "data": [product.model_dump() for product in products]}
        yield {"event": "done", "data": {"ok": True, "mode": "shopping_assist"}}

    def _continued_constraints(self, session) -> SearchConstraints:
        base = session.pending_constraints or session.constraints
        if not base.category and session.last_product_ids:
            product = self.products.get(session.last_product_ids[0])
            if product:
                base = SearchConstraints(category=product.category, sub_category=product.sub_category)
        return replace(base, exclude_product_ids=list(dict.fromkeys(session.last_product_ids)))

    def _continued_query(self, message: str, constraints: SearchConstraints) -> str:
        parts = [
            message,
            constraints.category or "",
            constraints.sub_category or "",
            " ".join(constraints.include_terms),
        ]
        return " ".join(part for part in parts if part).strip() or message

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
            yield {"event": "done", "data": {"ok": True, "mode": "product_qa"}}
            return

        rag = self.products.get_rag(product.product_id)
        rag["retrieved_chunks"] = self.products.get_chunks(product.product_id)
        text = self.product_qa.answer(message, product, rag)
        async for token in self._tokens(text):
            yield {"event": "token", "data": token}
        yield {"event": "products", "data": [product.model_dump()]}
        yield {"event": "done", "data": {"ok": True, "mode": "product_qa", "grounded_product_id": product.product_id}}

    def _sku_id_from_message(self, product, message: str) -> str | None:
        if not product or not product.skus:
            return None
        compact = self._normalize_sku_match_text(message)
        for sku in product.skus:
            candidates = [sku.sku_id, *[str(value) for value in sku.properties.values()]]
            for candidate in candidates:
                normalized = self._normalize_sku_match_text(candidate)
                if normalized and normalized in compact:
                    return sku.sku_id
        return None

    def _normalize_sku_match_text(self, text: str) -> str:
        compact = re.sub(r"[\s，。！？,.!?；;：:、/\\-]+", "", text.lower())
        return compact.replace("gb", "g").replace("tb", "t")

    def _sku_label(self, product, sku_id: str) -> str:
        sku = next((item for item in product.skus if item.sku_id == sku_id), None)
        if not sku:
            return ""
        return " / ".join(str(value) for value in sku.properties.values())

    def _is_checkout_followup(self, message: str) -> bool:
        compact = re.sub(r"[\s，。！？,.!?；;：:、]+", "", message.lower())
        if any(term in compact for term in ["确认下单", "确认订单", "确认", "下单", "取消下单", "取消结算", "不下单"]):
            return True
        return self._extract_checkout_address(message) is not None

    def _is_checkout_confirmation(self, message: str) -> bool:
        compact = re.sub(r"[\s，。！？,.!?；;：:、]+", "", message.lower())
        return compact in {"确认", "确认下单", "确认订单", "地址没问题", "没问题", "可以下单", "下单吧", "确认购买"}

    def _extract_checkout_address(self, message: str) -> str | None:
        text = re.sub(r"\s+", " ", message).strip(" ，。！？,.!?；;")
        if not text:
            return None
        compact = re.sub(r"[\s，。！？,.!?；;：:、]+", "", text.lower())
        if self._is_checkout_confirmation(text) or any(term in compact for term in ["取消下单", "取消结算", "不下单"]):
            return None
        match = re.search(r"(?:收货地址|收件地址|地址|寄到|送到|配送到)(?:是|为|:|：)?\s*(.+)", text, re.I)
        address = match.group(1).strip(" ，。！？,.!?；;") if match else text
        address_compact = re.sub(r"[\s，。！？,.!?；;：:、]+", "", address)
        address_hints = ["省", "市", "区", "县", "路", "街", "道", "号", "室", "小区", "镇", "村", "楼", "单元"]
        if len(address_compact) < 6 or not any(hint in address_compact for hint in address_hints):
            return None
        address = re.sub(r"^(我在|我的|就|改成|改为)", "", address).strip(" ，。！？,.!?；;")
        return address[:120] if address else None

    def _cart_order_summary(self, state) -> str:
        lines = ["订单汇总："]
        for index, item in enumerate(state.items[:6], start=1):
            title = self._short_text(item.product.title, 24)
            sku_text = self._sku_label(item.product, item.selected_sku.sku_id) if item.selected_sku else ""
            sku_suffix = f"（{sku_text}）" if sku_text else ""
            subtotal = item.unit_price * item.quantity
            lines.append(f"{index}. {title}{sku_suffix} x{item.quantity}，小计 ¥{subtotal:.0f}")
        if len(state.items) > 6:
            lines.append(f"还有 {len(state.items) - 6} 个商品条目未展开。")
        lines.append(f"合计 ¥{state.total_price:.0f}")
        return "\n".join(lines)

    def _short_text(self, text: str, max_chars: int) -> str:
        value = str(text or "").strip()
        if len(value) <= max_chars:
            return value
        return value[: max(1, max_chars - 1)] + "…"

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
        # Prompt boundary: the LLM only receives already-retrieved product facts
        # and the user constraints. It may polish wording, but `GroundingGuard`
        # must validate the final text against these product objects before the
        # answer can be cached or streamed; otherwise we use deterministic text.
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

    def _grounded_prefix(self, constraints) -> str:
        """Deterministic streaming prefix. Always states the local-catalog source,
        and—when the user gave exclusions—explicitly confirms they were honored, so
        the negative-constraint acknowledgement survives even if the LLM rephrases
        the answer without it."""
        prefix = "以下信息来自本地商品库。"
        excluded = list(dict.fromkeys(list(constraints.exclude_terms) + list(constraints.exclude_brands)))
        if excluded:
            prefix += f"已按你的要求排除{'、'.join(excluded)}相关商品。"
        return prefix

    def _fallback_response_text(self, message: str, products, constraints, include_exclusion: bool = True) -> str:
        names = "、".join(self._response_product_name(product) for product in products[:3])
        guard = "以下信息来自本地商品库。"
        evidence = self._recommendation_evidence_sentence(products)
        if "防晒" in message and products:
            return f"{guard} 根据你的需求，给你推荐这款防晒，价格和适用信息来自商品库：{names}。{evidence}"
        if "对比" in message or "哪个" in message:
            return f"{guard} 我先把更匹配的几款放在前面：{names}。你可以点开商品卡片看详情，也可以继续说“对比前两款”。"
        if "眼罩" in message:
            return f"{guard} 商品库暂时没有精确的眼罩商品，我先按睡眠/放松场景给你找相近候选：{names}。"
        if any(term in message for term in ["来源", "可靠", "可信", "证据"]):
            return f"{guard} 我优先按来源、SKU、评论和商品库证据排序，先看这几款：{names}。"
        if any(term in message for term in ["评价", "评论", "口碑", "稳"]):
            return f"{guard} 我会结合评论均分、评论数和风险提示来判断稳定性，先看这几款：{names}。"
        if include_exclusion and (constraints.exclude_terms or constraints.exclude_brands):
            excluded = "、".join(dict.fromkeys(constraints.exclude_terms + constraints.exclude_brands))
            return f"{guard} 我已经排除了 {excluded} 相关商品，优先推荐：{names}。{evidence}"
        return f"{guard} 根据你的需求，我优先推荐这几款：{names}。{evidence}"

    def _recommendation_evidence_sentence(self, products) -> str:
        if not products:
            return ""
        top = products[0]
        parts = []
        if top.reason:
            parts.append(top.reason)
        parts.extend(top.match_reasons[:2])
        if top.risk_flags:
            parts.append("注意：" + "、".join(top.risk_flags[:2]))
        evidence = "；".join(list(dict.fromkeys(part for part in parts if part))[:4])
        return f"我把第一款排在前面，是因为{evidence}。" if evidence else ""

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
        if self.intent.is_affirmative_confirmation(message) and self.intent.has_enough_signal(constraints):
            return None
        if self.intent.has_specific_product_signal(message, constraints):
            return None
        compact = re.sub(r"[\s，。！？,.!?]", "", message)
        specific_subcategories = {
            "防晒",
            "面霜",
            "精华",
            "眼霜",
            "卸妆",
            "洗面奶",
            "耳机",
            "蓝牙耳机",
            "充电设备",
            "充电器",
            "充电宝",
            "平板",
            "平板电脑",
            "笔记本",
            "笔记本电脑",
            "背包",
            "外套",
            "运动鞋",
            "跑鞋",
            "篮球鞋",
            "咖啡",
            "功能饮料",
            "坚果",
        }
        if constraints.sub_category in specific_subcategories:
            return None
        if any(term in compact for term in ["来源", "可靠", "可信", "证据"]):
            return None
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
            return "我是 ShopGuide 项目里的电商导购 Agent。对话模型可以在左上角设置里切换为 DeepSeek 或其他 OpenAI-compatible 模型；商品检索、工具调用和防幻觉检查仍由本机后端统一控制。"
        if compact in {"你是谁", "你能做什么", "怎么用", "帮助", "help"}:
            return "我是这个项目里的电商导购 Agent。你可以和我正常聊天：先说模糊需求也行，我会主动追问；也可以说预算、偏好、不要的品牌/成分，我会只从商品库里找可验证的商品。还可以说“记住我以后护肤不要酒精”“1000元预算去三亚配一套”。"
        if compact in {"谢谢", "谢了", "thanks", "thankyou"}:
            return "不客气。你继续补充偏好、让我对比前两款，或者说把某一款加入购物车都可以。"
        if any(term in compact for term in ["支付失败", "付款失败", "下单失败", "失败了怎么办", "支付不了怎么办"]):
            return "如果模拟支付失败，先回到购物车确认商品和 SKU 是否还在，再重新支付或重新生成订单。本项目不会产生真实扣款；失败订单只用于本地演示。"
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

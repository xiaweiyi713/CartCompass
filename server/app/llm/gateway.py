from __future__ import annotations

import time
from dataclasses import asdict
from typing import AsyncIterator

from pydantic import BaseModel

from app.agent.llm_client import ArkLLMClient, LLMGatewayError
from app.llm.router import ModelRouter
from app.llm.schemas import (
    ConstraintInput,
    ConstraintOutput,
    ConversationPlan,
    ConversationPlanInput,
    GroundedAnswerPacket,
    GroundedProductFact,
)
from app.llm.validators.json_validator import parse_model_json
from app.models.schemas import LLMConfigRequest, LLMStatus, LLMTestRequest, Product
from app.observability import observability
from app.rag.product_repository import SearchConstraints
from app.recovery import notice


_PLANNER_SYSTEM = (
    "你是电商导购助手的「对话规划器」。根据完整对话历史和用户最新一句话，判断这一轮意图，"
    "只输出一个 JSON 对象（不要 Markdown、不要解释）。\n"
    "字段：\n"
    "- intent，从以下选一个：smalltalk(闲聊/情绪/寒暄，无购物意图)、product_knowledge(问商品/成分/参数等知识但没说要买)、"
    "weather(问天气)、recommend(想买/挑选/找商品/推荐/筛选)、compare(对比已出现的商品)、"
    "cart(加购/改数量/删除/下单/结算)、product_qa(追问上一轮某款商品的评价/来源/规格/是否适合)、"
    "after_sale(退换货/保修/售后)、budget_plan(给定预算配一套)、travel_bundle(出行/旅行带什么)、"
    "feedback(对上一轮推荐反馈：太贵/换品牌/平替/升级/不喜欢)、clarify(有购物意向但信息太少需先追问)。\n"
    "- shopping_intent_level：0=纯闲聊；1-2=模糊兴趣(先口头帮忙别急着出商品)；3=明确想看商品；4=交易。\n"
    "- reply：仅当 intent 是 smalltalk/product_knowledge/weather/clarify 时，写一段自然、简洁、口语化的中文回复；"
    "其余 intent 一律留空字符串（商品文案由后端生成）。\n"
    "- rationale：一句话判断依据。\n"
    "原则：① 自然融合——用户只是闲聊或表达情绪时 intent=smalltalk、level=0，给共情/陪聊回复，绝不硬推商品，"
    "可在合适时轻轻一句“需要的话我可以帮你挑”。② 顺着上下文——若历史刚推荐过商品，用户说“第二款”“刚才那个”“再便宜点”，"
    "结合历史判断为 compare/cart/product_qa/feedback。③ 不要编造：reply 里不得出现具体商品名、价格、优惠、库存。"
    "④ 拿不准但像购物：用 clarify，并在 reply 里礼貌追问预算/类目/偏好。\n"
    "示例(只示意字段，实际请结合历史)：\n"
    '用户“今天好累啊不想动” → {"intent":"smalltalk","shopping_intent_level":0,"reply":"辛苦啦，先歇会儿~需要的话我随时帮你挑点东西","rationale":"纯情绪闲聊"}\n'
    '用户“我下周去三亚玩几天” → {"intent":"smalltalk","shopping_intent_level":1,"reply":"三亚不错呀！要是想让我帮你按天气配齐防晒、穿搭和出行用品，说一声就行","rationale":"只是分享行程，未明确要买，可轻提供帮助"}\n'
    '用户“去三亚帮我配齐要带的东西” → {"intent":"travel_bundle","shopping_intent_level":3,"reply":"","rationale":"明确要按出行配清单"}\n'
    '用户“推荐降噪耳机，1000以内” → {"intent":"recommend","shopping_intent_level":3,"reply":"","rationale":"明确找商品"}\n'
    '历史里刚推荐过耳机，用户“第二款有差评吗” → {"intent":"product_qa","shopping_intent_level":3,"reply":"","rationale":"追问上一轮第二款"}\n'
    '用户“把第一款加到购物车” → {"intent":"cart","shopping_intent_level":4,"reply":"","rationale":"加购操作"}'
)


class LLMGateway:
    """Task-level LLM gateway.

    Business logic remains in AgentOrchestrator and retrieval/ranking. This
    facade limits model calls to narrow tasks and validates structured output
    before the rest of the system can use it.
    """

    def __init__(self, provider_gateway: ArkLLMClient | None = None) -> None:
        self.provider_gateway = provider_gateway or ArkLLMClient()
        self.router = ModelRouter()

    @property
    def is_configured(self) -> bool:
        return self.provider_gateway.is_configured

    @property
    def model(self) -> str | None:
        return self.provider_gateway.model

    def status(self, session_id: str = "default") -> LLMStatus:
        return self.provider_gateway.status(session_id)

    def configure(self, request: LLMConfigRequest) -> LLMStatus:
        return self.provider_gateway.configure(request)

    def clear(self, session_id: str) -> LLMStatus:
        return self.provider_gateway.clear(session_id)

    async def test_connection(self, request: LLMTestRequest) -> dict:
        return await self.provider_gateway.test_connection(request)

    async def parse_constraints(self, input_data: ConstraintInput, session_id: str = "default") -> ConstraintOutput | None:
        return await self._safe_structured_call(
            task="constraint_parsing",
            session_id=session_id,
            schema=ConstraintOutput,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是电商检索约束抽取器。只输出 json，不推荐商品。"
                        "字段包括 category, sub_category, price_min, price_max, include_preferences, "
                        "exclude_brands, exclude_terms, sort_preference。"
                    ),
                },
                {"role": "user", "content": input_data.model_dump_json()},
            ],
        )

    async def plan_turn(self, input_data: ConversationPlanInput, session_id: str = "default") -> ConversationPlan | None:
        """LLM conversation planner: classify intent in context and (for chat
        turns) draft a natural reply. Returns None when the model is unconfigured
        or the output fails schema validation, so the caller can fall back to the
        deterministic rule router."""
        return await self._safe_structured_call(
            task="conversation_planning",
            session_id=session_id,
            schema=ConversationPlan,
            messages=[
                {"role": "system", "content": _PLANNER_SYSTEM},
                {"role": "user", "content": input_data.model_dump_json()},
            ],
        )

    async def recommendation_reply(
        self,
        user_message: str,
        products: list[Product],
        constraints: SearchConstraints,
        session_id: str = "default",
    ) -> str | None:
        packet = self._grounded_answer_packet(user_message, products[:3], constraints)
        return await self.generate_grounded_answer(packet, session_id=session_id)

    async def stream_recommendation_reply(
        self,
        user_message: str,
        products: list[Product],
        constraints: SearchConstraints,
        session_id: str = "default",
    ) -> AsyncIterator[str]:
        packet = self._grounded_answer_packet(user_message, products[:3], constraints)
        async for chunk in self.stream_grounded_answer(packet, session_id=session_id):
            yield chunk

    async def generate_grounded_answer(self, packet: GroundedAnswerPacket, session_id: str = "default") -> str | None:
        config = self.provider_gateway._config_for_session(session_id)
        if not config.is_configured:
            return None
        messages = [
            {
                "role": "system",
                "content": (
                    "你是智购罗盘 CartCompass 的受控回答生成器。你只能基于 grounded_answer_packet 回答。"
                    "不要选择新商品，不要生成商品卡片，不要编造优惠、库存、销量、参数或承诺。"
                    "如果证据不足，明确说当前商品库缺少该信息。输出自然中文，简洁。"
                    "直接给用户可读答案，不要输出自检、审稿、核对过程、输出规范、最终整理说明或两版重复答案。"
                    "最多推荐 3 个商品，每个商品用一两句话说明价格和理由。"
                ),
            },
            {"role": "user", "content": packet.model_dump_json()},
        ]
        started_at = time.perf_counter()
        try:
            result = await self.provider_gateway._chat(
                config,
                messages=messages,
                temperature=self.router.temperature_for_task("answer_generation"),
                max_tokens=380,
            )
        except LLMGatewayError:
            observability.increment("llm_grounded_answer_failures")
            return None
        observability.increment("llm_grounded_answer_success")
        observability.record_latency("llm_grounded_answer_latency_ms", result.latency_ms)
        observability.add_current_step(
            "llm_grounded_answer",
            {
                "provider": result.provider,
                "model": result.model,
                "latency_ms": round(result.latency_ms, 2),
                "task": packet.task,
                "product_ids": [product.product_id for product in packet.selected_products],
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        return result.text

    async def stream_grounded_answer(self, packet: GroundedAnswerPacket, session_id: str = "default") -> AsyncIterator[str]:
        config = self.provider_gateway._config_for_session(session_id)
        if not config.is_configured:
            return
        messages = [
            {
                "role": "system",
                "content": (
                    "你是智购罗盘 CartCompass 的受控回答生成器。你只能基于 grounded_answer_packet 回答。"
                    "不要选择新商品，不要生成商品卡片，不要编造优惠、库存、销量、参数或承诺。"
                    "如果证据不足，明确说当前商品库缺少该信息。输出自然中文，简洁。"
                    "直接给用户可读答案，不要输出自检、审稿、核对过程、输出规范、最终整理说明或两版重复答案。"
                    "最多推荐 3 个商品，每个商品用一两句话说明价格和理由。"
                ),
            },
            {"role": "user", "content": packet.model_dump_json()},
        ]
        started_at = time.perf_counter()
        first_chunk_seen = False
        chunk_count = 0
        try:
            async for chunk in self.provider_gateway._chat_stream(
                config,
                messages=messages,
                temperature=self.router.temperature_for_task("answer_generation"),
                max_tokens=380,
            ):
                if not first_chunk_seen:
                    first_chunk_seen = True
                    first_chunk_ms = (time.perf_counter() - started_at) * 1000
                    observability.record_latency("llm_grounded_answer_first_chunk_latency_ms", first_chunk_ms)
                    observability.add_current_step("llm_stream_first_chunk", {"latency_ms": round(first_chunk_ms, 2)})
                chunk_count += 1
                yield chunk
        except LLMGatewayError as exc:
            observability.increment("llm_grounded_answer_stream_failures")
            observability.add_current_step("llm_stream_error", {"message": str(exc)})
            return

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        if chunk_count:
            observability.increment("llm_grounded_answer_stream_success")
            observability.record_latency("llm_grounded_answer_stream_latency_ms", elapsed_ms)
            observability.add_current_step(
                "llm_grounded_answer_stream",
                {
                    "provider": config.provider,
                    "model": config.model,
                    "latency_ms": round(elapsed_ms, 2),
                    "task": packet.task,
                    "product_ids": [product.product_id for product in packet.selected_products],
                    "chunks": chunk_count,
                },
            )

    async def travel_need_plan(self, user_message: str, session_id: str = "default") -> dict | None:
        return await self.provider_gateway.travel_need_plan(user_message, session_id=session_id)

    async def general_chat(self, user_message: str, mode: str, session_id: str = "default") -> str | None:
        config = self.provider_gateway._config_for_session(session_id)
        if not config.is_configured:
            return None
        if mode == "product_knowledge":
            system = (
                "你是智购罗盘 CartCompass 的商品知识助手。回答商品、消费、护肤、数码或生活选购知识。"
                "不要推荐具体商品，不要生成商品卡片，不要编造商品库没有的价格、库存或优惠。"
                "如果用户之后想购买，可以自然提示他补充预算、偏好或排除条件。"
            )
            temperature = 0.3
        else:
            system = (
                "你是智购罗盘 CartCompass，一个购物导向但不强推商品的对话助手。"
                "普通聊天时正常回应，不要硬卖货，不要推荐具体商品。"
                "如果话题和消费决策有关，可以轻量提示用户需要时可继续让你筛选。"
                "避免医疗诊断、金融投资等高风险结论。回答简洁自然。"
            )
            temperature = 0.5
        try:
            result = await self.provider_gateway._chat(
                config,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=360,
            )
        except LLMGatewayError:
            observability.increment("llm_general_chat_failures")
            return None
        observability.increment("llm_general_chat_success")
        observability.record_latency("llm_general_chat_latency_ms", result.latency_ms)
        observability.add_current_step(
            "llm_general_chat",
            {
                "provider": result.provider,
                "model": result.model,
                "mode": mode,
                "latency_ms": round(result.latency_ms, 2),
            },
        )
        return result.text

    async def _safe_structured_call(
        self,
        task: str,
        session_id: str,
        schema: type[BaseModel],
        messages: list[dict],
    ):
        config = self.provider_gateway._config_for_session(session_id)
        if not config.is_configured:
            return None
        started_at = time.perf_counter()
        try:
            result = await self.provider_gateway._chat(
                config,
                messages=messages,
                temperature=self.router.temperature_for_task(task),
                max_tokens=360,
                response_format_json=True,
            )
        except LLMGatewayError:
            observability.increment(f"llm_{task}_failures")
            return None
        parsed = parse_model_json(result.text, schema)
        repaired = False
        repair_latency_ms = None
        if parsed is None:
            repair_result = await self._repair_structured_output(
                task=task,
                session_id=session_id,
                schema=schema,
                raw_text=result.text,
            )
            if repair_result:
                repaired = True
                repair_latency_ms = repair_result.latency_ms
                parsed = parse_model_json(repair_result.text, schema)
        observability.add_current_step(
            "llm_structured_task",
            {
                "task": task,
                "provider": result.provider,
                "model": result.model,
                "latency_ms": round(result.latency_ms, 2),
                "schema_valid": parsed is not None,
                "repaired": repaired,
                "repair_latency_ms": round(repair_latency_ms, 2) if repair_latency_ms is not None else None,
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        if parsed is None:
            observability.increment(f"llm_{task}_schema_invalid")
            observability.add_current_step(
                "fallback",
                {
                    "code": "structured_output_failed",
                    "task": task,
                    "notice": notice("structured_output_failed").model_dump(),
                },
            )
            return None
        observability.increment(f"llm_{task}_success")
        return parsed

    async def _repair_structured_output(
        self,
        task: str,
        session_id: str,
        schema: type[BaseModel],
        raw_text: str,
    ):
        config = self.provider_gateway._config_for_session(session_id)
        schema_json = schema.model_json_schema()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 JSON 修复器。把用户给出的模型输出修复为符合 schema 的 json。"
                    "只输出 json 对象，不要 Markdown，不要解释。无法确定的字段用 null、false、空数组或合理默认值。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"task={task}\n"
                    f"schema={schema_json}\n"
                    f"raw_output={raw_text[:4000]}"
                ),
            },
        ]
        try:
            result = await self.provider_gateway._chat(
                config,
                messages=messages,
                temperature=0.0,
                max_tokens=360,
                response_format_json=True,
            )
        except LLMGatewayError:
            observability.increment(f"llm_{task}_repair_failures")
            return None
        observability.increment(f"llm_{task}_repair_attempts")
        return result

    def _grounded_answer_packet(
        self,
        user_message: str,
        products: list[Product],
        constraints: SearchConstraints,
    ) -> GroundedAnswerPacket:
        return GroundedAnswerPacket(
            task="recommendation",
            user_query=user_message,
            constraints=asdict(constraints),
            selected_products=[self._grounded_product_fact(product) for product in products],
        )

    def _grounded_product_fact(self, product: Product) -> GroundedProductFact:
        return GroundedProductFact(
            product_id=product.product_id,
            name=product.title,
            brand=product.brand,
            category=product.category,
            sub_category=product.sub_category,
            price=product.base_price,
            source_name=product.source_name,
            evidence=product.evidence[:3],
            match_reasons=product.match_reasons[:5],
            risk_flags=product.risk_flags[:5],
        )

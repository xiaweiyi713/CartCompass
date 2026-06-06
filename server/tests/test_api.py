from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.llm_client import ArkLLMClient, LLMCallResult, LLMConfig
from app.agent.recommendation_cache import RecommendationCache
from app.agent.user_profile import UserProfileService
from app.llm.gateway import LLMGateway
from app.llm.schemas import ConstraintOutput, GroundedAnswerPacket
from app.main import app
from app.api.routes import agent, image_search_service
from app.models.schemas import CurrentWeather, WeatherContext, WeatherImplications, WeatherLocation
from app.rag.product_repository import SearchConstraints


client = TestClient(app)


def _stream_tokens(text: str) -> str:
    chunks = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line.removeprefix("data: "))
        if isinstance(payload, str):
            chunks.append(payload)
    return "".join(chunks)


def _stream_products(text: str) -> list[dict]:
    products: list[dict] = []
    last_event = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            last_event = line.removeprefix("event: ")
        elif last_event == "products" and line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
            if isinstance(payload, list):
                products.extend(item for item in payload if isinstance(item, dict))
    return products


def _stream_fallbacks(text: str) -> list[dict]:
    fallbacks: list[dict] = []
    last_event = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            last_event = line.removeprefix("event: ")
        elif last_event == "fallback" and line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
            if isinstance(payload, dict):
                fallbacks.append(payload)
    return fallbacks


def _stream_event_payloads(text: str, event_name: str) -> list:
    payloads: list = []
    last_event = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            last_event = line.removeprefix("event: ")
        elif last_event == event_name and line.startswith("data: "):
            payloads.append(json.loads(line.removeprefix("data: ")))
    return payloads


def test_health_reports_products() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["product_count"] >= 100
    assert "llm_configured" in data
    assert "llm" in data


def test_llm_gateway_runtime_config_masks_key_and_can_clear() -> None:
    session_id = "test-llm-runtime-config"
    response = client.post(
        "/api/llm/config",
        json={
            "session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-secret-value",
            "model": "deepseek-chat",
        },
    )
    assert response.status_code == 200
    status = response.json()
    assert status["configured"] is True
    assert status["provider"] == "deepseek"
    assert status["model"] == "deepseek-chat"
    assert status["base_url"] == "https://api.deepseek.com"
    assert status["key_present"] is True
    assert "secret" not in str(status).lower()

    fetched = client.get("/api/llm/status", params={"session_id": session_id})
    assert fetched.status_code == 200
    assert fetched.json()["provider"] == "deepseek"

    cleared = client.delete(f"/api/llm/config/{session_id}")
    assert cleared.status_code == 200
    assert cleared.json()["source"] == "env"


def test_llm_gateway_sanitizes_pasted_key_text() -> None:
    session_id = "test-llm-sanitized-key"
    response = client.post(
        "/api/llm/config",
        json={
            "session_id": session_id,
            "provider": "deepseek",
            "api_key": "API： sk-real-secret-value\u200b\n",
            "model": "deepseek-chat",
        },
    )
    assert response.status_code == 200
    status = response.json()
    assert status["configured"] is True
    assert status["key_hint"] == "sk-...alue"

    cleared = client.delete(f"/api/llm/config/{session_id}")
    assert cleared.status_code == 200


def test_llm_connection_without_key_returns_recoverable_fallback() -> None:
    response = client.post(
        "/api/llm/test",
        json={
            "session_id": "test-llm-no-key-fallback",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_key": "",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["fallback"]["code"] == "model_config_failed"
    assert payload["fallback"]["actions"]


def test_llm_travel_need_plan_accepts_common_model_json_variants() -> None:
    llm = ArkLLMClient()
    raw = """
    {
      "destination": "新疆",
      "scenario": "旅行",
      "intro_focus": "新疆地域广阔，气候干燥，日照强烈，需注意防晒和补水",
      "slots": [
        {
          "role": "防晒护肤",
          "category": "美妆护肤/防晒",
          "sub_category": "防晒霜",
          "search_terms": ["新疆旅行防晒", "高倍防晒霜", "户外防晒"],
          "reason": "新疆紫外线强"
        },
        {
          "role": "户外装备",
          "category": "服饰运动/null",
          "sub_category": "运动鞋",
          "search_terms": ["新疆徒步鞋", "户外运动鞋"],
          "reason": "需要步行"
        },
        {
          "role": "充电设备",
          "category": "数码电子/充电宝",
          "sub_category": "充电宝",
          "search_terms": ["大容量充电宝", "旅行充电宝"],
          "reason": "长途补电"
        },
        {
          "role": "路上补能",
          "category": "食品饮料/null",
          "sub_category": null,
          "search_terms": ["坚果", "补能"],
          "reason": "路上吃"
        }
      ]
    }
    """
    plan = llm._parse_travel_need_plan(raw)
    assert plan is not None
    assert plan["destination"] == "新疆"
    assert [slot["category"] for slot in plan["slots"]] == ["美妆护肤", "服饰运动", "数码电子", "食品饮料"]
    assert [slot["sub_category"] for slot in plan["slots"]] == ["防晒", "徒步鞋", "充电设备", "坚果/零食"]
    assert "新疆旅行防晒" in plan["slots"][0]["search_terms"]


def test_llm_gateway_grounded_packet_contains_only_selected_backend_products() -> None:
    gateway = LLMGateway()
    selected = [agent.products.get("p_digital_016"), agent.products.get("p_digital_015")]
    selected = [product for product in selected if product]
    packet = gateway._grounded_answer_packet(
        "推荐续航好的手机，8000以内",
        selected,
        SearchConstraints(category="数码电子", sub_category="智能手机", max_price=8000, include_terms=["续航"]),
    )

    assert isinstance(packet, GroundedAnswerPacket)
    assert [product.product_id for product in packet.selected_products] == ["p_digital_016", "p_digital_015"]
    assert packet.constraints["max_price"] == 8000
    assert all(product.price <= 8000 for product in packet.selected_products)
    assert any("不要生成商品卡片字段" in rule for rule in packet.forbidden)


def test_llm_gateway_repairs_invalid_structured_json_before_fallback() -> None:
    class FakeProviderGateway:
        def __init__(self) -> None:
            self.response_format_flags: list[bool] = []
            self.calls = 0

        def _config_for_session(self, session_id: str) -> LLMConfig:
            return LLMConfig(provider="deepseek", model="deepseek-chat", api_key="sk-test", base_url="https://api.deepseek.com")

        async def _chat(
            self,
            config: LLMConfig,
            messages: list[dict],
            temperature: float,
            max_tokens: int,
            response_format_json: bool = False,
        ) -> LLMCallResult:
            self.calls += 1
            self.response_format_flags.append(response_format_json)
            text = "category=phone price_max=4000" if self.calls == 1 else '{"category":"数码电子","sub_category":"手机","price_max":4000}'
            return LLMCallResult(text=text, provider=config.provider, model=config.model or "", latency_ms=12.0)

    fake = FakeProviderGateway()
    gateway = LLMGateway(fake)  # type: ignore[arg-type]
    parsed = asyncio.run(
        gateway._safe_structured_call(
            task="constraint_parsing",
            session_id="test",
            schema=ConstraintOutput,
            messages=[{"role": "user", "content": "4000以内手机"}],
        )
    )

    assert parsed is not None
    assert parsed.category == "数码电子"
    assert parsed.price_max == 4000
    assert fake.calls == 2
    assert fake.response_format_flags == [True, True]


def test_llm_client_extracts_streaming_deltas() -> None:
    llm = ArkLLMClient()

    assert llm._stream_delta_from_line('data: {"choices":[{"delta":{"content":"以下"}}]}') == "以下"
    assert llm._stream_delta_from_line('data: {"choices":[{"delta":{"reasoning_content":"思考"}}]}') == "思考"
    assert llm._stream_delta_from_line("data: [DONE]") is None
    assert llm._anthropic_stream_delta_from_line('data: {"type":"content_block_delta","delta":{"text":"推荐"}}') == "推荐"


def test_llm_gateway_streams_grounded_answer_chunks() -> None:
    class FakeProviderGateway:
        def _config_for_session(self, session_id: str) -> LLMConfig:
            return LLMConfig(provider="deepseek", model="deepseek-chat", api_key="sk-test", base_url="https://api.deepseek.com")

        async def _chat_stream(
            self,
            config: LLMConfig,
            messages: list[dict],
            temperature: float,
            max_tokens: int,
        ):
            yield "以下商品信息"
            yield "来自本地商品库。"

    async def collect() -> list[str]:
        selected = [agent.products.get("p_digital_016")]
        selected = [product for product in selected if product]
        gateway = LLMGateway(FakeProviderGateway())  # type: ignore[arg-type]
        return [
            chunk
            async for chunk in gateway.stream_recommendation_reply(
                "推荐续航好的手机",
                selected,
                SearchConstraints(category="数码电子", sub_category="智能手机"),
                session_id="test",
            )
        ]

    assert asyncio.run(collect()) == ["以下商品信息", "来自本地商品库。"]


def test_chat_stream_blocks_unsafe_llm_stream_before_emitting_risky_terms(monkeypatch) -> None:
    original_stream = agent.llm.stream_recommendation_reply
    agent.reply_cache._items.clear()

    async def unsafe_stream(*args, **kwargs):
        yield "这几款可以领券，"
        yield "还有库存充足。"

    monkeypatch.setattr(agent.llm, "stream_recommendation_reply", unsafe_stream)
    try:
        response = client.post(
            "/api/chat/stream",
            json={"session_id": "test-unsafe-stream-guard", "message": "推荐适合油皮的防晒，200元以内"},
        )
    finally:
        agent.llm.stream_recommendation_reply = original_stream

    assert response.status_code == 200
    token_text = _stream_tokens(response.text)
    assert "领券" not in token_text
    assert "库存充足" not in token_text
    assert "根据你的需求" in token_text or "以下价格和商品信息都来自本地商品库" in token_text


def test_chat_stream_buffers_numeric_claim_before_flush(monkeypatch) -> None:
    original_stream = agent.llm.stream_recommendation_reply
    agent.reply_cache._items.clear()

    async def split_price_stream(*args, **kwargs):
        yield "这款今天只要99"
        yield "元包邮。"

    monkeypatch.setattr(agent.llm, "stream_recommendation_reply", split_price_stream)
    try:
        response = client.post(
            "/api/chat/stream",
            json={"session_id": "test-split-price-stream-guard", "message": "推荐适合油皮的防晒，200元以内"},
        )
    finally:
        agent.llm.stream_recommendation_reply = original_stream

    assert response.status_code == 200
    token_text = _stream_tokens(response.text)
    assert "99" not in token_text
    assert "包邮" not in token_text
    assert "根据你的需求" in token_text or "以下价格和商品信息都来自本地商品库" in token_text


def test_chat_stream_drops_internal_model_review_segments(monkeypatch) -> None:
    original_stream = agent.llm.stream_recommendation_reply
    agent.reply_cache._items.clear()

    async def review_leaking_stream(*args, **kwargs):
        yield "推荐内容已整理完成，所有内容均严格依据给定参数。"
        yield "为你推荐这款防晒，价格和适用信息来自商品库。"

    monkeypatch.setattr(agent.llm, "stream_recommendation_reply", review_leaking_stream)
    try:
        response = client.post(
            "/api/chat/stream",
            json={"session_id": "test-internal-review-stream", "message": "推荐适合油皮的防晒，200元以内"},
        )
    finally:
        agent.llm.stream_recommendation_reply = original_stream

    assert response.status_code == 200
    token_text = _stream_tokens(response.text)
    assert "推荐内容已整理完成" not in token_text
    assert "严格依据给定参数" not in token_text
    assert "你推荐这款防晒" in token_text


def test_chat_stream_waits_for_user_facing_answer_start(monkeypatch) -> None:
    original_stream = agent.llm.stream_recommendation_reply
    agent.reply_cache._items.clear()

    async def preamble_stream(*args, **kwargs):
        yield "第一款为售价199元的候选，适配当前需求。"
        yield "第二款推荐内容均基于给定资料，无额外编造信息。"
        yield "给你推荐这款防晒，价格和适用信息来自商品库。"

    monkeypatch.setattr(agent.llm, "stream_recommendation_reply", preamble_stream)
    try:
        response = client.post(
            "/api/chat/stream",
            json={"session_id": "test-model-preamble-stream", "message": "推荐适合油皮的防晒，200元以内"},
        )
    finally:
        agent.llm.stream_recommendation_reply = original_stream

    assert response.status_code == 200
    token_text = _stream_tokens(response.text)
    assert "第一款为售价199元" not in token_text
    assert "给定资料" not in token_text
    assert "你推荐这款防晒" in token_text


def test_orchestrator_strips_internal_model_review_text() -> None:
    raw = (
        "以下信息来自本地商品库。"
        "当前需要为用户推荐5000左右、符合3250-6750元预算的手机。"
        "我已核对两款推荐手机的配置、售价及对应人群均符合给定信息要求，输出规范无误。"
        "符合预算区间的第二款推荐机型已补充完成，最终整理出两款适配不同需求的手机推荐内容，直接按此输出即可。"
        "我已经整理好两款手机的推荐话术，无额外补充。"
        "为你推荐小米17 Max，售价6499元，适合影音游戏。"
    )

    cleaned = agent.output_sanitizer.strip_internal_review_text(raw)

    assert "已核对" not in cleaned
    assert "输出规范" not in cleaned
    assert "当前需要为用户" not in cleaned
    assert "推荐话术" not in cleaned
    assert "按此输出" not in cleaned
    assert "为你推荐小米17 Max" in cleaned


def test_orchestrator_strips_duplicate_model_preamble() -> None:
    raw = (
        "以下信息来自本地商品库。"
        "第一款为售价6499元的小米17 Max，适配影音游戏爱好者。"
        "第二款为OPPO Reno 16 Pro。"
        "给你推荐两款符合预算区间的手机：1. 小米17 Max，售价6499元。"
    )

    cleaned = agent.output_sanitizer.strip_internal_review_text(raw)

    assert cleaned.startswith("以下信息来自本地商品库。给你推荐两款")
    assert "第一款为售价6499元" not in cleaned


def test_recommendation_cache_uses_stable_key_and_ttl() -> None:
    cache = RecommendationCache(max_entries=2, ttl_seconds=60)
    product = agent.products.get("p_digital_016")
    assert product is not None
    key = cache.key(
        message=" 推荐续航好的手机 ",
        constraints=SearchConstraints(category="数码电子", include_terms=["续航", "拍照"]),
        products=[product],
        model_identity={"configured": True, "provider": "deepseek", "model": "deepseek-chat"},
    )
    same_key = cache.key(
        message="推荐续航好的手机",
        constraints=SearchConstraints(category="数码电子", include_terms=["拍照", "续航"]),
        products=[product],
        model_identity={"configured": True, "provider": "deepseek", "model": "deepseek-chat"},
    )

    cache.set(key, "缓存回复", "llm")

    assert key == same_key
    assert cache.get(same_key).text == "缓存回复"


def test_llm_gateway_accepts_anthropic_runtime_config() -> None:
    session_id = "test-llm-anthropic-config"
    response = client.post(
        "/api/llm/config",
        json={
            "session_id": session_id,
            "provider": "anthropic",
            "api_key": "sk-ant-test-secret-value",
            "model": "claude-3-5-sonnet-latest",
            # Pin the endpoint explicitly so the assertion stays hermetic and does
            # not depend on an ambient ANTHROPIC_BASE_URL env var on the test host.
            "base_url": "https://api.anthropic.com/v1",
        },
    )
    assert response.status_code == 200
    status = response.json()
    assert status["configured"] is True
    assert status["provider"] == "anthropic"
    assert status["base_url"] == "https://api.anthropic.com/v1"
    assert "secret" not in str(status).lower()

    cleared = client.delete(f"/api/llm/config/{session_id}")
    assert cleared.status_code == 200


def test_llm_constraint_refinement_only_fills_missing_fields() -> None:
    parsed = SearchConstraints(category="数码电子", include_terms=["续航"], exclude_terms=["酒精"])
    output = ConstraintOutput(
        category="美妆护肤",
        sub_category="智能手机",
        price_max=4000,
        include_preferences=["拍照", "续航"],
        exclude_brands=["小米"],
        exclude_terms=["厚重"],
    )

    refined = agent._merge_llm_constraints(parsed, output)

    assert refined.category == "数码电子"
    assert refined.sub_category == "智能手机"
    assert refined.max_price == 4000
    assert refined.include_terms == ["续航", "拍照"]
    assert refined.exclude_terms == ["酒精", "厚重"]
    assert refined.exclude_brands == ["小米"]


def test_llm_gateway_disabled_test_does_not_call_network() -> None:
    response = client.post("/api/llm/test", json={"session_id": "test-llm-disabled", "provider": "disabled"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "未配置" in payload["message"]


def test_products_endpoint_searches_crawled_products() -> None:
    response = client.get("/api/products", params={"query": "Anker 100W 快充", "category": "数码电子", "limit": 3})
    assert response.status_code == 200
    products = response.json()
    product_ids = [product["product_id"] for product in products]
    assert "p_anker_003_a24c9a01" in product_ids
    anker = next(product for product in products if product["product_id"] == "p_anker_003_a24c9a01")
    assert anker["match_score"] > 0
    assert any("快充" in reason or "充电器" in reason for reason in anker["match_reasons"])
    assert any("混合检索" in reason for reason in anker["match_reasons"])
    assert "risk_flags" in anker


def test_product_alternatives_endpoint_returns_substitutes() -> None:
    response = client.get("/api/products/p_beauty_006/alternatives", params={"mode": "cheaper", "limit": 3})
    assert response.status_code == 200
    products = response.json()["products"]
    assert products
    assert all(product["product_id"] != "p_beauty_006" for product in products)
    assert products[0]["base_price"] < 170
    assert "平替" in products[0]["reason"]


def test_after_sale_policy_is_grounded_and_cautious() -> None:
    response = client.get("/api/products/p_digital_003/after_sale", params={"question": "这款能退换货吗"})
    assert response.status_code == 200
    data = response.json()
    assert "Demo" in data["answer"]
    assert "不承诺真实平台" in data["answer"]
    assert data["policy"]["product_id"] == "p_digital_003"


def test_virtual_checkout_session_and_mock_payment_complete_order() -> None:
    session_id = "test-virtual-checkout"
    add = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_digital_003", "sku_id": "s_p_digital_003_1", "quantity": 1},
    )
    assert add.status_code == 200

    checkout = client.post(
        "/api/checkout/session",
        json={"session_id": session_id, "user_id": "demo_user", "address": "北京市朝阳区 Demo 路 1 号", "payment_mode": "mock"},
    )
    assert checkout.status_code == 200
    payload = checkout.json()
    assert payload["checkout_session_id"].startswith("cs_demo_")
    assert payload["checkout_url"].endswith(f"/checkout/{payload['checkout_session_id']}")
    assert payload["total_amount"] == 9999
    assert any("SKU" in item for item in payload["review"])

    page = client.get(f"/checkout/{payload['checkout_session_id']}")
    assert page.status_code == 200
    assert page.headers["content-type"].lower().startswith("text/html; charset=utf-8")
    assert page.content.startswith(b"<!doctype html>")
    assert "CartCompass Virtual Mall" in page.text
    assert "不会产生真实扣款" in page.text
    assert "æ²ç®±" not in page.text

    paid = client.post(f"/api/checkout/{payload['checkout_session_id']}/pay/mock", json={"outcome": "success"})
    assert paid.status_code == 200
    order = paid.json()
    assert order["payment_status"] == "PAID_TEST"
    assert order["checkout_session_id"] == payload["checkout_session_id"]
    assert order["post_purchase_recommendations"]

    success_page = client.get(f"/checkout/success?session_id={payload['checkout_session_id']}")
    assert success_page.status_code == 200
    assert success_page.headers["content-type"].lower().startswith("text/html; charset=utf-8")
    assert success_page.content.startswith(b"<!doctype html>")
    assert "支付成功" in success_page.text
    assert f"shopguide://checkout/success?order_id={order['order_id']}" in success_page.text
    assert "æ¯ä»" not in success_page.text

    fetched = client.get(f"/api/orders/{order['order_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["order_id"] == order["order_id"]

    cart_after_payment = client.get(f"/api/cart/{session_id}")
    assert cart_after_payment.status_code == 200
    assert cart_after_payment.json()["items"] == []


def test_virtual_checkout_mock_failure_keeps_cart() -> None:
    session_id = "test-virtual-checkout-failure"
    client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_beauty_006", "sku_id": "s_p_beauty_006_1", "quantity": 1},
    )
    checkout = client.post("/api/checkout/session", json={"session_id": session_id, "payment_mode": "mock"})
    assert checkout.status_code == 200
    checkout_id = checkout.json()["checkout_session_id"]

    failed = client.post(f"/api/checkout/{checkout_id}/pay/mock", json={"outcome": "failed"})
    assert failed.status_code == 200
    assert failed.json()["status"] == "FAILED"
    assert "余额不足" in failed.json()["failure_reason"]

    cart_after_failure = client.get(f"/api/cart/{session_id}")
    assert cart_after_failure.status_code == 200
    assert cart_after_failure.json()["items"]


def test_product_skus_expose_real_variant_images() -> None:
    response = client.get("/api/products/p_digital_003")
    assert response.status_code == 200
    skus = response.json()["skus"]
    assert len(skus) == 9
    assert all(sku["image_url"].endswith(".png") for sku in skus)
    assert all("store.storeimages.cdn-apple.com" in sku["image_source_url"] for sku in skus)
    assert {sku["properties"]["颜色"] for sku in skus} == {"宇宙橙 Cosmic Orange", "冰川蓝", "银色"}


def test_iphone_17_pro_skus_expose_real_variant_images() -> None:
    response = client.get("/api/products/p_digital_001")
    assert response.status_code == 200
    skus = response.json()["skus"]
    assert len(skus) == 9
    assert all(sku["image_url"].endswith(".png") for sku in skus)
    assert all("store.storeimages.cdn-apple.com" in sku["image_source_url"] for sku in skus)
    assert {sku["properties"]["颜色"] for sku in skus} == {"宇宙橙 Cosmic Orange", "冰川蓝", "银色"}


def test_product_skus_fallback_to_real_product_image_when_variant_image_missing() -> None:
    response = client.get("/api/products/p_digital_005")
    assert response.status_code == 200
    product = response.json()
    assert product["skus"]
    assert all(sku["image_url"] == product["image_url"] for sku in product["skus"])


def test_products_expose_grounding_sources() -> None:
    response = client.get("/api/products/p_real_254_ca23a519")
    assert response.status_code == 200
    product = response.json()
    assert product["source_url"] == "https://www.lacolombe.com/products/colombia-inga-red-honey"
    assert product["source_name"] == "lacolombe.com"
    assert product["evidence"]


def test_products_expose_mock_stock_fields() -> None:
    response = client.get("/api/products/p_digital_016")
    assert response.status_code == 200
    product = response.json()
    assert product["stock_status"] in {"in_stock", "low_stock", "out_of_stock"}
    assert isinstance(product["inventory_count"], int)
    assert product["inventory_count"] >= 0


def test_chat_stream_clarifies_broad_phone_request() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-chat-clarify", "message": "推荐手机"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "event: token" in text
    assert "更看重" in answer
    assert "拍照" in answer
    assert "预算" in answer
    assert "event: products" not in text


def test_chat_stream_model_identity_is_smalltalk_without_products() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-model-identity", "message": "你是什么模型"})
    assert response.status_code == 200
    text = response.text
    token_text = _stream_tokens(text)
    assert "CartCompass" in token_text
    assert "对话模型" in token_text
    assert "event: products" not in text


def test_general_chat_does_not_force_product_recommendations() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-general-chat", "message": "今天心情有点烦"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "event: products" not in text
    assert '"mode": "general_chat"' in text
    assert any(term in answer for term in ["状态", "舒服", "继续说", "正常聊天", "休息"])


def test_product_knowledge_explains_without_product_cards() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-product-knowledge", "message": "防晒 SPF50 是什么意思"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "event: products" not in text
    assert '"mode": "product_knowledge"' in text
    assert "SPF" in answer or "防晒" in answer


def test_weather_queries_do_not_let_llm_hallucinate_city_results(monkeypatch) -> None:
    async def fake_lookup(location: str, days: int = 7):
        if location == "三亚":
            return WeatherContext(
                location=WeatherLocation(name="三亚", country="中国", latitude=18.25, longitude=109.51, timezone="Asia/Shanghai"),
                current=CurrentWeather(
                    temperature_c=30,
                    apparent_temperature_c=34,
                    humidity=78,
                    precipitation_mm=0,
                    wind_speed_kmh=12,
                    condition="多云",
                ),
                implications=WeatherImplications(tags=["高温"], shopping_needs=["防晒"], travel_advice=[]),
                source="TestWeather",
                fetched_at="2026-05-28T00:00:00Z",
            )
        return None

    monkeypatch.setattr(agent.weather, "lookup", fake_lookup)

    sanya = client.post("/api/chat/stream", json={"session_id": "test-weather-sanya", "message": "三亚今天天气怎么样"})
    chengdu = client.post("/api/chat/stream", json={"session_id": "test-weather-chengdu", "message": "成都今天天气怎么样"})

    sanya_answer = _stream_tokens(sanya.text)
    chengdu_answer = _stream_tokens(chengdu.text)
    assert "TestWeather" in sanya_answer
    assert "30°C" in sanya_answer
    assert "event: weather" in sanya.text
    assert "暂时没有查到成都的实时天气" in chengdu_answer
    assert "event: products" not in sanya.text
    assert "event: products" not in chengdu.text


def test_weather_query_without_location_asks_for_city() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-weather-no-city", "message": "今天天气怎么样"})
    answer = _stream_tokens(response.text)
    assert "城市" in answer or "目的地" in answer
    assert "event: products" not in response.text


def test_weather_positive_statement_stays_general_chat() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-weather-smalltalk", "message": "今天天气真好"})
    assert response.status_code == 200
    answer = _stream_tokens(response.text)
    assert '"mode": "general_chat"' in response.text
    assert "实时天气" not in answer
    assert "没有查到" not in answer
    assert "event: weather" not in response.text
    assert "event: products" not in response.text


def test_weather_location_followup_uses_previous_weather_context(monkeypatch) -> None:
    async def fake_lookup(location: str, days: int = 7):
        if "德国" in location:
            return WeatherContext(
                location=WeatherLocation(name="柏林", country="德国", latitude=52.52, longitude=13.405, timezone="Europe/Berlin"),
                current=CurrentWeather(
                    temperature_c=25,
                    apparent_temperature_c=23,
                    humidity=33,
                    precipitation_mm=0,
                    wind_speed_kmh=10,
                    condition="多云",
                ),
                implications=WeatherImplications(tags=["紫外线强"], shopping_needs=["防晒霜"], travel_advice=[]),
                source="TestWeather",
                fetched_at="2026-06-02T12:19:00Z",
            )
        if "意大利" in location:
            return WeatherContext(
                location=WeatherLocation(name="罗马", country="意大利", latitude=41.9028, longitude=12.4964, timezone="Europe/Rome"),
                current=CurrentWeather(
                    temperature_c=28,
                    apparent_temperature_c=29,
                    humidity=45,
                    precipitation_mm=0,
                    wind_speed_kmh=8,
                    condition="晴",
                ),
                implications=WeatherImplications(tags=["紫外线强"], shopping_needs=["防晒霜"], travel_advice=[]),
                source="TestWeather",
                fetched_at="2026-06-02T12:20:00Z",
            )
        return None

    monkeypatch.setattr(agent.weather, "lookup", fake_lookup)

    session_id = "test-weather-followup-italy"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "德国今天天气怎么样"})
    second = client.post("/api/chat/stream", json={"session_id": session_id, "message": "意大利呢"})

    first_answer = _stream_tokens(first.text)
    second_answer = _stream_tokens(second.text)
    assert "柏林当前天气" in first_answer
    assert "罗马当前天气" in second_answer
    assert "TestWeather" in second_answer
    assert '"mode": "weather_query"' in second.text
    assert "event: weather" in second.text
    assert "event: products" not in second.text


def test_weak_purchase_intent_clarifies_before_recommending() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-weak-purchase", "message": "我最近想运动，但不知道买什么"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "event: products" not in text
    assert '"mode": "weak_purchase_intent"' in text
    assert "跑步" in answer and "预算" in answer


def test_chat_stream_tokenizes_chinese_like_typing() -> None:
    units = agent._stream_units("可以，我先帮你缩小范围：iPhone 17 Pro。")
    assert units[:6] == ["可", "以", "，", "我", "先", "帮"]
    assert "iPhone" in units
    assert "17" in units
    assert "。" in units
    assert max(len(unit) for unit in units if not unit.isascii()) == 1


def test_chat_stream_uses_clarified_context() -> None:
    session_id = "test-chat-context"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "拍照优先，预算4000"})
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "p_digital" in text


def test_response_product_alignment_filters_cards_to_llm_mentions() -> None:
    products = [
        agent.products.get("p_digital_001"),
        agent.products.get("p_digital_009"),
        agent.products.get("p_digital_015"),
        agent.products.get("p_digital_017"),
        agent.products.get("p_digital_002"),
    ]
    candidates = [product for product in products if product]
    text = "推荐小米 17 Max、OPPO Find X9 Ultra 和 vivo X300 Ultra 这三款长续航手机。"
    aligned = agent._align_products_with_response(text, candidates)
    assert [product.product_id for product in aligned] == ["p_digital_009", "p_digital_015", "p_digital_017"]


def test_response_product_alignment_does_not_match_brand_only() -> None:
    candidates = [
        agent.products.get("p_digital_016"),
        agent.products.get("p_digital_015"),
    ]
    candidates = [product for product in candidates if product]

    exact = agent._align_products_with_response("推荐 OPPO Find X9 Ultra 这款长续航手机。", candidates)
    assert [product.product_id for product in exact] == ["p_digital_015"]

    brand_only = agent._align_products_with_response("推荐 OPPO 的长续航手机。", candidates)
    assert [product.product_id for product in brand_only] == ["p_digital_016", "p_digital_015"]


def test_fallback_recommendation_text_and_cards_share_same_products() -> None:
    session_id = "test-fallback-text-card-consistency"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "9999"})
    assert response.status_code == 200
    answer = _stream_tokens(response.text)
    products = _stream_products(response.text)
    assert len(products) == 3
    for product in products:
        stored = agent.products.get(product["product_id"])
        assert stored is not None
        assert agent._response_product_name(stored) in answer


def test_chat_stream_understands_phone_followups() -> None:
    session_id = "test-phone-followups"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in first.text

    budget = client.post("/api/chat/stream", json={"session_id": session_id, "message": "9999"})
    assert budget.status_code == 200
    assert "event: products" in budget.text
    assert "智能手机" in budget.text
    assert "真无线耳机" not in budget.text
    assert "蓝牙耳机" not in budget.text

    gaming = client.post("/api/chat/stream", json={"session_id": session_id, "message": "游戏"})
    assert gaming.status_code == 200
    assert "event: products" in gaming.text
    assert "智能手机" in gaming.text
    assert "真无线耳机" not in gaming.text
    assert "蓝牙耳机" not in gaming.text


def test_phone_feature_followup_prioritizes_evidence_backed_battery_life() -> None:
    session_id = "test-phone-battery-business-logic"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "续航"})
    assert response.status_code == 200
    answer = _stream_tokens(response.text)
    products = _stream_products(response.text)
    assert len(products) >= 3
    assert "Apple iPhone 17 Pro" not in answer
    for product in products[:3]:
        stored = agent.products.get(product["product_id"])
        assert stored is not None
        text = agent._product_text_for_business(stored)
        assert any(term in text for term in ["续航", "大电池", "电池", "省电", "功耗"])
        assert agent._response_product_name(stored) in answer


def test_phone_budget_followup_text_cards_and_budget_are_consistent() -> None:
    session_id = "test-phone-budget-business-logic"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "9999"})
    assert response.status_code == 200
    answer = _stream_tokens(response.text)
    products = _stream_products(response.text)
    assert len(products) == 3
    assert all(product["base_price"] <= 9999 for product in products)
    for product in products:
        stored = agent.products.get(product["product_id"])
        assert stored is not None
        assert agent._response_product_name(stored) in answer


def test_premium_phone_budget_followups_rank_near_budget_tier() -> None:
    session_id = "test-premium-phone-budget-tier"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in first.text

    response_9000 = client.post("/api/chat/stream", json={"session_id": session_id, "message": "9000"})
    assert response_9000.status_code == 200
    products_9000 = _stream_products(response_9000.text)
    assert products_9000
    assert products_9000[0]["base_price"] == 8999
    assert all(product["base_price"] <= 9000 for product in products_9000)

    response_10000 = client.post("/api/chat/stream", json={"session_id": session_id, "message": "10000"})
    assert response_10000.status_code == 200
    products_10000 = _stream_products(response_10000.text)
    assert products_10000
    assert any(product["base_price"] == 9999 for product in products_10000[:3])
    assert all(product["base_price"] <= 10000 for product in products_10000)


def test_phone_budget_particle_followup_keeps_active_context() -> None:
    session_id = "test-phone-budget-particle-followup"
    first = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "推荐5000左右的手机，拍照和续航都要好一点"},
    )
    assert first.status_code == 200
    first_products = _stream_products(first.text)
    assert len(first_products) >= 2
    assert all(3250 <= product["base_price"] <= 6750 for product in first_products)

    followup = client.post("/api/chat/stream", json={"session_id": session_id, "message": "8000呢"})
    assert followup.status_code == 200
    text = followup.text
    products = _stream_products(text)
    assert "event: products" in text
    assert '"mode": "general_chat"' not in text
    assert products
    assert all(product["category"] == "数码电子" for product in products)
    assert all(product["sub_category"] in {"智能手机", "手机"} for product in products)
    assert all(product["base_price"] <= 8000 for product in products)


def test_chat_stream_does_not_clarify_specific_apple_phone_request() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-specific-apple-phone", "message": "我要苹果手机"})
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "needs_clarification" not in text
    assert "Apple" in text or "苹果" in text
    assert '"brand": "小米"' not in text
    assert '"brand": "OPPO"' not in text


def test_chat_stream_uses_specific_phone_model_followup() -> None:
    session_id = "test-specific-model-followup"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "苹果手机"})
    assert "event: products" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "17"})
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "needs_clarification" not in text
    assert "iPhone 17" in text
    assert '"brand": "小米"' not in text


def test_explicit_brand_request_overrides_long_term_brand_exclusion() -> None:
    session_id = "test-explicit-brand-overrides-profile"
    remember = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "记住我以后买数码不要苹果"},
    )
    assert "苹果" in remember.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "我要苹果手机"})
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "Apple" in text or "苹果" in text
    assert "排除了 苹果" not in text


def test_profile_ingredient_preference_applies_across_categories_and_can_be_overridden(tmp_path) -> None:
    profiles = UserProfileService(tmp_path / "profiles.json")
    profiles.remember_from_message("u1", "记住我以后推荐不要含香精")

    applied = profiles.apply_to_constraints(
        "u1",
        SearchConstraints(category="食品饮料"),
        message="推荐咖啡",
    )
    assert "香精" in applied.exclude_terms

    overridden = profiles.apply_to_constraints(
        "u1",
        SearchConstraints(category="食品饮料"),
        message="推荐含香精的饮料",
    )
    assert "香精" not in overridden.exclude_terms

    explicit_negative = profiles.apply_to_constraints(
        "u1",
        SearchConstraints(category="食品饮料", exclude_terms=["香精"]),
        message="推荐不含香精的饮料",
    )
    assert "香精" in explicit_negative.exclude_terms


def test_profile_budget_requires_budget_context(tmp_path) -> None:
    profiles = UserProfileService(tmp_path / "profiles.json")

    _, no_updates = profiles.remember_from_message("u1", "记住我喜欢 iPhone 17")
    _, updates = profiles.remember_from_message("u1", "记住我以后数码预算5000左右")

    assert not any("预算" in update for update in no_updates)
    assert any("数码预算约 5000 元" in update for update in updates)


def test_profile_save_is_atomic_json(tmp_path) -> None:
    path = tmp_path / "profiles.json"
    profiles = UserProfileService(path)

    profiles.remember_from_message("u1", "记住我以后护肤品不要含酒精，我是油皮，预算200")

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["u1"]["skin_type"] == "油皮"
    assert not list(tmp_path.glob(".profiles.json.*.tmp"))


def test_constraint_parser_does_not_treat_wireless_or_sugar_free_as_negative() -> None:
    wireless = agent.parser.parse("推荐真无线耳机")
    sugar_free = agent.parser.parse("推荐无糖咖啡")
    alcohol_free = agent.parser.parse("推荐无酒精防晒")

    assert wireless.exclude_terms == []
    assert sugar_free.exclude_terms == []
    assert "酒精" in alcohol_free.exclude_terms


def test_demo_catalog_contains_only_challenge_categories() -> None:
    categories = {product.category for product in agent.products.all()}

    assert categories == {"美妆护肤", "数码电子", "服饰运动", "食品饮料"}


def test_chat_stream_understands_iphone_17pm_alias() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-17pm", "message": "我要看17p\u2006m"})
    assert response.status_code == 200
    assert "event: products" in response.text
    assert "iPhone 17 Pro Max" in response.text


def test_chat_stream_accepts_no_preference_followup() -> None:
    session_id = "test-no-preference"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "随便"})
    assert response.status_code == 200
    assert "event: products" in response.text
    assert "智能手机" in response.text


def test_chat_stream_excludes_only_requested_brand() -> None:
    response = client.post("/api/chat/stream", json={"session_id": "test-exclude-xiaomi", "message": "苹果手机不要小米"})
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "Apple" in text or "苹果" in text
    assert '"brand": "小米"' not in text


def test_chat_stream_travel_request_does_not_reuse_phone_context() -> None:
    session_id = "test-travel-topic-switch"
    phone = client.post("/api/chat/stream", json={"session_id": session_id, "message": "17pm"})
    assert "智能手机" in phone.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐去三亚要带的东西"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "event: products" in text
    assert "上一轮手机偏好" in answer
    assert "防晒" in answer
    assert "智能手机" not in text


def test_chat_stream_japan_packing_request_overrides_pending_phone_clarification() -> None:
    session_id = "test-japan-topic-switch"
    phone = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in phone.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐一下去日本要带的东西"})
    assert response.status_code == 200
    text = response.text
    token_text = _stream_tokens(text)
    assert "event: products" in text
    assert "needs_clarification" not in text
    assert "日本" in token_text
    assert "上一轮手机偏好" in token_text
    assert "三亚" not in token_text
    assert "智能手机" not in text


def test_chat_stream_japan_vacation_intro_does_not_hardcode_sanya() -> None:
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "test-japan-vacation", "message": "推荐一下日本度假要带的东西"},
    )
    assert response.status_code == 200
    text = response.text
    token_text = _stream_tokens(text)
    assert "event: products" in text
    assert "日本" in token_text
    assert "度假" in token_text
    assert "三亚" not in token_text


def test_chat_stream_japan_what_to_buy_uses_travel_bundle_cards() -> None:
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "test-japan-what-to-buy", "message": "我想去日本，应该买什么"},
    )
    assert response.status_code == 200
    text = response.text
    token_text = _stream_tokens(text)
    products = _stream_products(text)
    categories = {(product["category"], product["sub_category"]) for product in products}
    assert "event: products" in text
    assert "日本" in token_text
    assert "不会把它误判成单品手机需求" in token_text
    assert products
    assert ("美妆护肤", "防晒") in categories
    assert ("服饰运动", "背包") in categories or any(product["category"] == "服饰运动" for product in products)
    assert not any(product["sub_category"] in {"笔记本电脑", "智能手机", "平板电脑"} for product in products)


def test_chat_stream_campus_starter_request_returns_checklist_products() -> None:
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "test-campus-starter", "message": "上大学要买什么啊"},
    )
    assert response.status_code == 200
    text = response.text
    token_text = _stream_tokens(text)
    products = _stream_products(text)
    categories = {(product["category"], product["sub_category"]) for product in products}
    assert "event: products" in text
    assert '"mode": "shopping_assist"' in text
    assert '"mode": "general_chat"' not in text
    assert "入学" in token_text or "校园" in token_text
    assert len(products) >= 3
    assert ("服饰运动", "背包") in categories
    assert ("数码电子", "充电设备") in categories
    assert any(product["category"] == "食品饮料" for product in products)
    assert not any(product["sub_category"] in {"智能手机", "平板电脑"} for product in products)


def test_non_food_gift_request_resets_food_context() -> None:
    session_id = "test-non-food-gift-context-reset"
    first = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "推荐适合送人的零食礼物"},
    )
    assert first.status_code == 200
    assert "event: products" in first.text
    assert any(product["category"] == "食品饮料" for product in _stream_products(first.text))

    response = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "我要送别人不是食物的礼物 有什么推荐"},
    )
    assert response.status_code == 200
    text = response.text
    token_text = _stream_tokens(text)
    products = _stream_products(text)
    assert "event: products" in text
    assert '"mode": "shopping_assist"' in text
    assert "非食品" in token_text or "不是食物" in token_text
    assert "重置" in token_text or "不会沿用" in token_text
    assert products
    assert not any(product["category"] == "食品饮料" for product in products)
    assert any(product["category"] in {"数码电子", "服饰运动", "美妆护肤"} for product in products)


def test_chat_stream_builds_budget_shopping_plan() -> None:
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "test-budget-plan", "message": "我1000元预算，下周去三亚，帮我配一套防晒和出行用品"},
    )
    assert response.status_code == 200
    text = response.text
    assert "event: plan" in text
    assert "三亚旅行 1000 元预算方案" in text
    assert "event: products" in text
    assert "防晒" in text
    assert "total_price" in text
    assert "智能手机" not in text


def test_chat_stream_builds_destination_specific_budget_plan() -> None:
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "test-budget-plan-japan", "message": "我1000元预算，下周去日本，帮我配一套出行用品清单"},
    )
    assert response.status_code == 200
    text = response.text
    assert "event: plan" in text
    assert "日本旅行 1000 元预算方案" in text
    assert "三亚旅行" not in text
    assert "event: products" in text
    assert "智能手机" not in text


def test_chat_stream_remembers_and_applies_user_profile() -> None:
    session_id = "test-profile-memory"
    remember = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "记住我以后护肤品不要含酒精，我是油皮，预算200"},
    )
    assert remember.status_code == 200
    assert "event: profile" in remember.text
    assert "酒精" in remember.text
    assert "油皮" in remember.text

    profile = client.get(f"/api/profile/{session_id}")
    assert profile.status_code == 200
    assert profile.json()["skin_type"] == "油皮"
    assert "酒精" in profile.json()["excluded_ingredients"]

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐防晒"})
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "p_beauty_006" in text

    clear = client.delete(f"/api/profile/{session_id}")
    assert clear.status_code == 200
    assert clear.json()["excluded_ingredients"] == []


def test_chat_stream_implicitly_remembers_allergy_profile() -> None:
    session_id = "test-implicit-allergy-profile"
    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "我酒精过敏"})
    assert response.status_code == 200
    answer = _stream_tokens(response.text)
    assert "event: profile" in response.text
    assert "长期偏好" in answer or "已经记住" in answer
    assert "酒精" in answer

    profile = client.get(f"/api/profile/{session_id}")
    assert profile.status_code == 200
    assert "酒精" in profile.json()["excluded_ingredients"]


def test_profile_manual_edit_applies_to_chat_profile_user_id() -> None:
    user_id = "test-manual-profile-user"
    session_id = "test-manual-profile-chat-session"

    added = client.post(f"/api/profile/{user_id}/preferences", json={"text": "酒精过敏"})
    assert added.status_code == 200
    assert "酒精" in added.json()["excluded_ingredients"]

    response = client.post(
        "/api/chat/stream",
        json={
            "session_id": session_id,
            "profile_user_id": user_id,
            "message": "推荐适合油皮的防晒，200元以内",
        },
    )
    assert response.status_code == 200
    text = response.text.replace("不含酒精", "")
    assert "event: products" in response.text
    assert "含酒精" not in text

    removed = client.post(
        f"/api/profile/{user_id}/preferences/delete",
        json={"kind": "excluded_ingredients", "value": "酒精"},
    )
    assert removed.status_code == 200
    assert "酒精" not in removed.json()["excluded_ingredients"]


def test_chat_stream_sunscreen_request_resets_phone_context() -> None:
    session_id = "test-sunscreen-topic-switch"
    client.post("/api/chat/stream", json={"session_id": session_id, "message": "17pm"})

    response = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "推荐适合油皮的防晒，200元以内，不要含酒精"},
    )
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "p_beauty_006" in text
    assert "智能手机" not in text
    assert "match_score" in text
    assert "match_reasons" in text
    assert "risk_flags" in text


def test_chat_stream_answers_product_review_followup() -> None:
    session_id = "test-product-review-followup"
    first = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "推荐适合油皮的防晒，200元以内，不要含酒精"},
    )
    assert "p_beauty_006" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "第一款差评主要说什么"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "event: token" in text
    assert "商品库" in answer
    assert "差评" in answer or "低分" in answer
    assert "过敏" in answer or "搓泥" in answer
    assert "event: products" in text


def test_chat_stream_answers_after_sale_followup() -> None:
    session_id = "test-after-sale-followup"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "我要看17pm"})
    assert "p_digital_003" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "第一款售后和保修怎么说"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "Demo" in text
    assert "不承诺真实平台" in answer
    assert "event: products" in text


def test_chat_stream_feedback_finds_cheaper_alternatives() -> None:
    session_id = "test-feedback-cheaper"
    first = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "推荐适合油皮的防晒，200元以内，不要含酒精"},
    )
    assert "p_beauty_006" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "第一款太贵了，有没有平替"})
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "平替" in text
    assert "last_feedback" in text


def test_budget_only_followup_after_alternative_keeps_phone_context() -> None:
    session_id = "test-budget-followup-after-phone-alternative"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in first.text

    phone = client.post("/api/chat/stream", json={"session_id": session_id, "message": "预算7700，拍照优先"})
    assert "event: products" in phone.text
    assert "智能手机" in phone.text

    cheaper = client.post("/api/chat/stream", json={"session_id": session_id, "message": "有没有再便宜点的"})
    assert "event: products" in cheaper.text
    assert "平替" in cheaper.text

    around = client.post("/api/chat/stream", json={"session_id": session_id, "message": "要5000左右的"})
    assert around.status_code == 200
    text = around.text
    products = _stream_products(text)
    assert "needs_clarification" not in text
    assert "打算入手什么品类" not in text
    assert products
    assert all(product["category"] == "数码电子" for product in products)
    assert all(product["sub_category"] in {"智能手机", "手机"} for product in products)


def test_phone_budget_de_suffix_followup_keeps_phone_context() -> None:
    session_id = "test-phone-budget-de-suffix-followup"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐5000以内的手机"})
    assert "event: products" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "7000的"})
    assert response.status_code == 200
    text = response.text
    products = _stream_products(text)
    assert "needs_clarification" not in text
    assert '"mode": "general_chat"' not in text
    assert products
    assert all(product["category"] == "数码电子" for product in products)
    assert all(product["sub_category"] in {"智能手机", "手机"} for product in products)
    assert all(product["base_price"] <= 7000 for product in products)


def test_affirmative_followup_continues_active_shopping_context() -> None:
    session_id = "test-affirmative-shopping-context"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐手机"})
    assert "needs_clarification" in first.text

    budget = client.post("/api/chat/stream", json={"session_id": session_id, "message": "7000的"})
    assert "event: products" in budget.text
    assert "needs_clarification" not in budget.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "是的"})
    assert response.status_code == 200
    text = response.text
    products = _stream_products(text)
    assert '"mode": "general_chat"' not in text
    assert "needs_clarification" not in text
    assert products
    assert all(product["category"] == "数码电子" for product in products)
    assert all(product["sub_category"] in {"智能手机", "手机"} for product in products)


def test_more_results_followup_uses_previous_recommendation_context() -> None:
    session_id = "test-more-results-phone-context"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐9999以内的手机"})
    assert "event: products" in first.text
    previous_ids = {product["product_id"] for product in _stream_products(first.text)}
    assert previous_ids

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "再多几个"})
    assert response.status_code == 200
    text = response.text
    products = _stream_products(text)
    assert "needs_clarification" not in text
    assert '"mode": "general_chat"' not in text
    assert products
    assert all(product["category"] == "数码电子" for product in products)
    assert all(product["sub_category"] in {"智能手机", "手机"} for product in products)
    assert not previous_ids.intersection(product["product_id"] for product in products)


def test_approximate_budget_parser_accepts_generic_numeric_forms() -> None:
    cases = [
        ("要6000左右的", 6000),
        ("7k左右", 7000),
        ("七千价位", 7000),
        ("一万上下", 10000),
    ]
    for message, expected in cases:
        constraints = agent.parser.parse(message)
        assert constraints.min_price == expected * 0.65
        assert constraints.max_price == expected * 1.35

    plain_budget = agent.parser.parse("预算500送女生礼物")
    assert plain_budget.max_price == 500
    assert plain_budget.min_price is None


def test_chat_stream_feedback_switches_brand() -> None:
    session_id = "test-feedback-brand"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐 Anker 100W 快充"})
    assert "Anker" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "换个品牌"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "event: products" in text
    assert "避开" in answer
    assert '"brand": "Anker"' not in text


def test_end_to_end_sunscreen_rejection_alternative_cart_and_checkout_flow() -> None:
    session_id = "test-e2e-sunscreen-commerce"
    first = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "推荐适合油皮的防晒，200元以内，不要含酒精"},
    )
    assert first.status_code == 200
    first_products = _stream_products(first.text)
    assert first_products
    assert first_products[0]["product_id"] == "p_beauty_006"
    assert all(product["base_price"] <= 200 for product in first_products)

    reject = client.post("/api/chat/stream", json={"session_id": session_id, "message": "不要欧莱雅，换个品牌"})
    assert reject.status_code == 200
    reject_answer = _stream_tokens(reject.text)
    alternatives = _stream_products(reject.text)
    assert "避开" in reject_answer
    assert alternatives
    assert all(product["brand"] != "巴黎欧莱雅" for product in alternatives)

    add = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": alternatives[0]["product_id"], "quantity": 1},
    )
    assert add.status_code == 200
    cart = add.json()
    assert len(cart["items"]) == 1
    assert cart["items"][0]["product"]["product_id"] == alternatives[0]["product_id"]

    checkout = client.post("/api/checkout/session", json={"session_id": session_id, "payment_mode": "mock"})
    assert checkout.status_code == 200
    checkout_payload = checkout.json()
    assert checkout_payload["total_amount"] == alternatives[0]["base_price"]

    paid = client.post(f"/api/checkout/{checkout_payload['checkout_session_id']}/pay/mock", json={"outcome": "success"})
    assert paid.status_code == 200
    assert paid.json()["payment_status"] == "PAID_TEST"


def test_end_to_end_phone_sku_cart_quantity_and_mock_failure_flow() -> None:
    session_id = "test-e2e-phone-sku-commerce"
    recommend = client.post("/api/chat/stream", json={"session_id": session_id, "message": "我要看17pm"})
    assert recommend.status_code == 200
    products = _stream_products(recommend.text)
    assert products and products[0]["product_id"] == "p_digital_003"
    sku_id = products[0]["skus"][1]["sku_id"]

    add = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_digital_003", "sku_id": sku_id, "quantity": 1},
    )
    assert add.status_code == 200
    item = add.json()["items"][0]
    assert item["selected_sku"]["sku_id"] == sku_id
    assert item["selected_sku"]["image_url"]

    update = client.post(
        "/api/cart/update",
        json={"session_id": session_id, "product_id": "p_digital_003", "sku_id": sku_id, "quantity": 2},
    )
    assert update.status_code == 200
    assert update.json()["items"][0]["quantity"] == 2

    checkout = client.post("/api/checkout/session", json={"session_id": session_id, "payment_mode": "mock"})
    assert checkout.status_code == 200
    failed = client.post(f"/api/checkout/{checkout.json()['checkout_session_id']}/pay/mock", json={"outcome": "failed"})
    assert failed.status_code == 200
    assert failed.json()["status"] == "FAILED"

    cart_after_failure = client.get(f"/api/cart/{session_id}")
    assert cart_after_failure.status_code == 200
    assert cart_after_failure.json()["items"][0]["quantity"] == 2


def test_chat_stream_answers_attribute_followup_from_faq() -> None:
    session_id = "test-product-attribute-followup"
    first = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "推荐适合油皮的防晒，200元以内，不要含酒精"},
    )
    assert "p_beauty_006" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "这款适合敏感肌吗，有没有酒精"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "不含酒精" in answer
    assert "敏感肌" in answer
    assert "商品库" in answer


def test_chat_stream_answers_sku_followup() -> None:
    session_id = "test-product-sku-followup"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "我要看17pm"})
    assert "p_digital_003" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "第一款不同规格怎么选"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "event: token" in text
    assert "SKU" in answer
    assert "256GB" in answer
    assert "512GB" in answer
    assert "真实图片" in answer


def test_chat_stream_answers_source_followup() -> None:
    session_id = "test-product-source-followup"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐 Anker 100W 快充"})
    assert "p_anker_003_a24c9a01" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "第一款来源可靠吗"})
    assert response.status_code == 200
    text = response.text
    answer = _stream_tokens(text)
    assert "公开来源" in answer or "公开页面采集" in answer
    assert "anker.com" in text
    assert "event: products" in text


def test_product_chunks_are_materialized_for_grounded_qa() -> None:
    chunks = agent.products.get_chunks("p_anker_003_a24c9a01")
    assert chunks
    assert {chunk["chunk_type"] for chunk in chunks} & {"identity", "detail", "faq", "review"}

    session_id = "test-product-chunk-qa"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐 Anker 100W 快充"})
    assert "p_anker_003_a24c9a01" in first.text
    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "第一款快充证据是什么"})
    answer = _stream_tokens(response.text)
    assert "片段" in answer or "证据" in answer


def test_chat_stream_resets_context_when_category_changes() -> None:
    session_id = "test-topic-switch"
    first = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐一款保湿提亮的护肤品"})
    assert "event: products" in first.text

    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "推荐适合囤货的咖啡饮料"})
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "食品饮料" in text


def test_chat_stream_prefers_sports_for_sunscreen_sports_pants() -> None:
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "test-sports-pants", "message": "想买一条适合户外防晒的运动裤"},
    )
    assert response.status_code == 200
    text = response.text
    assert "event: products" in text
    assert "服饰运动" in text


def test_cart_crud_and_checkout() -> None:
    session_id = "test-cart-crud"

    add_response = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_digital_016", "quantity": 1},
    )
    assert add_response.status_code == 200
    assert add_response.json()["items"][0]["quantity"] == 1

    update_response = client.post(
        "/api/cart/update",
        json={"session_id": session_id, "product_id": "p_digital_016", "quantity": 3},
    )
    assert update_response.status_code == 200
    assert update_response.json()["items"][0]["quantity"] == 3

    remove_response = client.delete(f"/api/cart/{session_id}/p_digital_016")
    assert remove_response.status_code == 200
    assert remove_response.json()["items"] == []

    client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_digital_016", "quantity": 2},
    )
    checkout_response = client.post(
        "/api/cart/checkout",
        json={"session_id": session_id, "address": "默认地址"},
    )
    assert checkout_response.status_code == 200
    order = checkout_response.json()
    assert order["order_id"].startswith("SG")
    assert order["items"][0]["quantity"] == 2
    assert order["total_price"] == 6598.0
    assert order["post_purchase_recommendations"]
    assert all(product["product_id"] != "p_digital_016" for product in order["post_purchase_recommendations"])

    state_response = client.get(f"/api/cart/{session_id}")
    assert state_response.status_code == 200
    assert state_response.json()["items"] == []


def test_agent_guided_checkout_confirms_address_and_completes_order() -> None:
    session_id = "test-agent-guided-checkout"
    add_response = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_digital_016", "quantity": 1},
    )
    assert add_response.status_code == 200

    start = client.post("/api/chat/stream", json={"session_id": session_id, "message": "我要下单"})
    assert start.status_code == 200
    start_text = _stream_tokens(start.text)
    assert "收货地址" in start_text
    assert "订单汇总" in start_text
    assert "合计" in start_text
    assert client.get(f"/api/cart/{session_id}").json()["items"]

    address = client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "北京市朝阳区 Demo 路 1 号"},
    )
    assert address.status_code == 200
    address_text = _stream_tokens(address.text)
    assert "收货地址已更新" in address_text
    assert "确认下单" in address_text
    assert "订单汇总" in address_text
    assert client.get(f"/api/cart/{session_id}").json()["items"]

    confirm = client.post("/api/chat/stream", json={"session_id": session_id, "message": "确认下单"})
    assert confirm.status_code == 200
    confirm_text = _stream_tokens(confirm.text)
    order_events = _stream_event_payloads(confirm.text, "order")
    assert "模拟下单已完成" in confirm_text
    assert "订单号：SG" in confirm_text
    assert "北京市朝阳区 Demo 路 1 号" in confirm_text
    assert order_events and order_events[0]["order_id"].startswith("SG")
    assert order_events[0]["address"] == "北京市朝阳区 Demo 路 1 号"
    assert client.get(f"/api/cart/{session_id}").json()["items"] == []


def test_agent_guided_checkout_can_cancel_without_clearing_cart() -> None:
    session_id = "test-agent-guided-checkout-cancel"
    client.post("/api/cart/add", json={"session_id": session_id, "product_id": "p_digital_016", "quantity": 1})

    start = client.post("/api/chat/stream", json={"session_id": session_id, "message": "结算"})
    assert "收货地址" in _stream_tokens(start.text)

    cancel = client.post("/api/chat/stream", json={"session_id": session_id, "message": "取消下单"})
    cancel_text = _stream_tokens(cancel.text)
    assert "已取消" in cancel_text
    assert client.get(f"/api/cart/{session_id}").json()["items"]


def test_cart_rejects_quantity_above_mock_inventory() -> None:
    session_id = "test-cart-stock-guard"
    response = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_digital_016", "quantity": 999},
    )
    assert response.status_code == 404
    assert "库存" in response.json()["detail"]


def test_empty_checkout_is_rejected() -> None:
    response = client.post("/api/cart/checkout", json={"session_id": "test-empty-cart"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["fallback"]["code"] == "empty_cart_checkout"
    assert payload["fallback"]["actions"]


def test_cart_keeps_different_skus_as_separate_lines() -> None:
    session_id = "test-cart-skus"
    first = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_digital_003", "sku_id": "s_p_digital_003_1", "quantity": 1},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_digital_003", "sku_id": "s_p_digital_003_2", "quantity": 1},
    )
    assert second.status_code == 200
    state = second.json()
    assert len(state["items"]) == 2
    assert {item["selected_sku"]["sku_id"] for item in state["items"]} == {"s_p_digital_003_1", "s_p_digital_003_2"}
    assert state["total_price"] == 19998.0

    removed = client.delete(f"/api/cart/{session_id}/p_digital_003", params={"sku_id": "s_p_digital_003_1"})
    assert removed.status_code == 200
    assert [item["selected_sku"]["sku_id"] for item in removed.json()["items"]] == ["s_p_digital_003_2"]


def test_clear_cart() -> None:
    session_id = "test-clear-cart"
    client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": "p_beauty_006", "quantity": 1},
    )
    response = client.delete(f"/api/cart/{session_id}")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_image_search_returns_similar_product() -> None:
    image_path = Path("server/static/product_images/p_digital_016.jpg")
    with image_path.open("rb") as image:
        response = client.post("/api/image_search", files={"file": ("p_digital_016.jpg", image, "image/jpeg")})
    assert response.status_code == 200
    products = response.json()["products"]
    assert products
    assert products[0]["product_id"] == "p_digital_016"


def test_image_search_route_uses_async_service(monkeypatch) -> None:
    async def fake_search_async(image_bytes: bytes, query: str = "", limit: int = 5):  # noqa: ANN001
        assert image_bytes == b"fake-image"
        assert query == "手机"
        assert limit == 5
        return []

    monkeypatch.setattr(image_search_service, "search_async", fake_search_async)

    response = client.post(
        "/api/image_search?query=手机",
        files={"file": ("fake.jpg", b"fake-image", "image/jpeg")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["products"] == []
    assert payload["fallback"]["code"] == "image_empty"


def test_image_search_invalid_upload_returns_recoverable_fallback() -> None:
    response = client.post("/api/image_search", files={"file": ("bad.jpg", b"not-an-image", "image/jpeg")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["products"] == []
    assert payload["fallback"]["code"] == "image_failed"
    assert payload["fallback"]["actions"]


def test_chat_empty_recommendation_streams_recovery_actions() -> None:
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "test-empty-recovery", "message": "推荐1元以内的防晒霜，不要含酒精，不要日系品牌"},
    )
    assert response.status_code == 200
    fallbacks = _stream_fallbacks(response.text)
    assert fallbacks
    assert fallbacks[0]["code"] == "empty_recommendation"
    assert fallbacks[0]["actions"]


def test_mock_payment_failure_returns_recoverable_fallback() -> None:
    session_id = "test-payment-failure-fallback"
    client.post("/api/cart/add", json={"session_id": session_id, "product_id": "p_digital_016", "quantity": 1})
    checkout = client.post("/api/checkout/session", json={"session_id": session_id, "payment_mode": "mock"})
    assert checkout.status_code == 200
    failed = client.post(f"/api/checkout/{checkout.json()['checkout_session_id']}/pay/mock", json={"outcome": "failed"})
    assert failed.status_code == 200
    payload = failed.json()
    assert payload["status"] == "FAILED"
    assert payload["fallback"]["code"] == "payment_failed"
    assert payload["fallback"]["actions"]

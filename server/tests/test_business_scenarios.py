from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api.routes import agent
from app.main import app


client = TestClient(app)


def _chat(session_id: str, message: str) -> tuple[str, list[dict]]:
    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": message})
    assert response.status_code == 200
    answer = ""
    products: list[dict] = []
    last_event = ""
    for line in response.text.splitlines():
        if line.startswith("event: "):
            last_event = line.removeprefix("event: ")
            continue
        if not line.startswith("data: "):
            continue
        payload = json.loads(line.removeprefix("data: "))
        if isinstance(payload, str):
            answer += payload
        elif last_event == "products" and isinstance(payload, list):
            products = [item for item in payload if isinstance(item, dict)]
    return answer, products


def _stored_product_text(product_id: str) -> str:
    product = agent.products.get(product_id)
    assert product is not None
    return agent._product_text_for_business(product)


def _has_positive_alcohol_risk(text: str) -> bool:
    normalized = text.replace("不含酒精", "").replace("不含有酒精", "").replace("无酒精", "")
    return "含酒精" in normalized or "酒精成分" in normalized


def test_vague_gift_and_general_shopping_requests_clarify_without_random_cards() -> None:
    vague_queries = [
        "我想买个礼物",
        "预算500送女生礼物",
        "随便推荐点东西",
        "买点实用的",
        "帮我挑个东西",
    ]

    for index, query in enumerate(vague_queries):
        answer, products = _chat(f"business-vague-{index}", query)
        assert not products
        assert any(term in answer for term in ["缩小范围", "问清楚", "送给谁", "预算"])
        assert any(term in answer for term in ["数码", "护肤", "服饰", "食品", "零食"])


def test_gift_followup_can_narrow_to_beauty_with_negative_ingredient() -> None:
    session_id = "business-gift-followup-beauty"
    answer, products = _chat(session_id, "预算500送女生礼物")
    assert "问清楚" in answer
    assert not products

    answer, products = _chat(session_id, "护肤品，不要酒精，300以内")
    assert products
    assert all(product["category"] == "美妆护肤" for product in products)
    assert all(product["base_price"] <= 300 for product in products)
    assert "酒精" in answer
    for product in products:
        assert not _has_positive_alcohol_risk(_stored_product_text(product["product_id"]))


def test_phone_feature_budget_compare_cart_and_mock_payment_flow() -> None:
    session_id = "business-phone-full-flow"
    answer, products = _chat(session_id, "推荐手机")
    assert "更看重" in answer
    assert not products

    answer, products = _chat(session_id, "续航，预算8000")
    assert len(products) >= 3
    assert all(product["category"] == "数码电子" and product["sub_category"] == "智能手机" for product in products)
    assert all(product["base_price"] <= 8000 for product in products)
    assert "Apple iPhone 17 Pro" not in answer
    for product in products[:3]:
        assert any(term in _stored_product_text(product["product_id"]) for term in ["续航", "大电池", "电池", "省电", "功耗"])
        stored = agent.products.get(product["product_id"])
        assert stored is not None
        assert agent._response_product_name(stored) in answer

    compare_response = client.post("/api/chat/stream", json={"session_id": session_id, "message": "对比前两款"})
    assert compare_response.status_code == 200
    compare_answer = ""
    for line in compare_response.text.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
            if isinstance(payload, str):
                compare_answer += payload
    assert "event: compare" in compare_response.text
    assert any(term in compare_answer for term in ["对比", "更", "适合", "差异", "第一款", "第二款"])

    selected = products[0]
    sku_id = selected["skus"][0]["sku_id"] if selected.get("skus") else None
    add = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": selected["product_id"], "sku_id": sku_id, "quantity": 1},
    )
    assert add.status_code == 200
    item = add.json()["items"][0]
    assert item["product"]["product_id"] == selected["product_id"]
    if sku_id:
        assert item["selected_sku"]["sku_id"] == sku_id
        assert item["selected_sku"]["image_url"]

    checkout = client.post("/api/checkout/session", json={"session_id": session_id, "payment_mode": "mock"})
    assert checkout.status_code == 200
    checkout_id = checkout.json()["checkout_session_id"]
    failed = client.post(f"/api/checkout/{checkout_id}/pay/mock", json={"outcome": "failed"})
    assert failed.status_code == 200
    assert failed.json()["status"] == "FAILED"
    cart_after_failure = client.get(f"/api/cart/{session_id}")
    assert cart_after_failure.status_code == 200
    assert cart_after_failure.json()["items"]


def test_sunscreen_rejection_alternative_checkout_success_flow() -> None:
    session_id = "business-sunscreen-reject-checkout"
    answer, products = _chat(session_id, "推荐适合油皮的防晒，200元以内，不要含酒精")
    assert products
    assert all(product["category"] == "美妆护肤" for product in products)
    assert all(product["base_price"] <= 200 for product in products)
    for product in products:
        assert not _has_positive_alcohol_risk(_stored_product_text(product["product_id"]))

    answer, alternatives = _chat(session_id, "不要欧莱雅，换个品牌")
    assert alternatives
    assert "避开" in answer
    assert all(product["brand"] != "巴黎欧莱雅" for product in alternatives)

    add = client.post(
        "/api/cart/add",
        json={"session_id": session_id, "product_id": alternatives[0]["product_id"], "quantity": 1},
    )
    assert add.status_code == 200
    checkout = client.post("/api/checkout/session", json={"session_id": session_id, "payment_mode": "mock"})
    assert checkout.status_code == 200
    paid = client.post(f"/api/checkout/{checkout.json()['checkout_session_id']}/pay/mock", json={"outcome": "success"})
    assert paid.status_code == 200
    assert paid.json()["payment_status"] == "PAID_TEST"


def test_travel_context_does_not_leak_previous_phone_or_laptop_context() -> None:
    session_id = "business-travel-context-reset"
    answer, products = _chat(session_id, "推荐手机")
    assert "更看重" in answer
    assert not products

    answer, products = _chat(session_id, "推荐一下日本度假要带的东西")
    assert products
    assert any(term in answer for term in ["日本", "度假", "旅行", "防晒", "轻量"])
    forbidden = {"智能手机", "手机", "笔记本电脑", "平板电脑"}
    assert all(product["sub_category"] not in forbidden for product in products)


def test_generic_travel_destination_uses_packing_logic_instead_of_phone_clarification() -> None:
    travel_queries = [
        ("新疆", "我要去新疆玩，应该买些什么"),
        ("西藏", "下周去西藏旅行要带什么"),
        ("云南", "准备去云南玩，帮我推荐点出行用品"),
    ]

    for destination, query in travel_queries:
        answer, products = _chat(f"business-generic-travel-{destination}", query)
        assert products
        assert destination in answer
        assert "更看重拍照" not in answer
        assert any(term in answer for term in ["防晒", "保湿", "轻量", "补能", "充电", "防风"])
        forbidden = {"智能手机", "手机", "笔记本电脑", "平板电脑"}
        assert all(product["sub_category"] not in forbidden for product in products)


def test_travel_destinations_produce_scene_specific_product_mix() -> None:
    cases = [
        ("sanya", "我要去三亚度假，应该买些什么", {"防晒", "速干T恤", "帽子", "充电设备", "功能饮料"}),
        ("xinjiang", "我要去新疆玩，应该买些什么", {"防晒", "面霜", "徒步鞋", "充电设备", "坚果/零食"}),
        ("harbin", "我要去哈尔滨玩，应该买些什么", {"面霜", "瑜伽裤", "徒步鞋", "咖啡", "充电设备"}),
        ("japan", "我要去日本旅行，应该买些什么", {"背包", "运动鞋", "充电设备", "防晒", "咖啡"}),
        ("business", "我要去上海出差，应该买些什么", {"充电设备", "背包", "咖啡", "面霜"}),
    ]
    mixes: list[set[str]] = []

    for key, query, expected_subcategories in cases:
        answer, products = _chat(f"business-travel-mix-{key}", query)
        actual = {product["sub_category"] for product in products}
        mixes.append(actual)
        assert products
        assert len(actual & expected_subcategories) >= min(4, len(expected_subcategories))
        assert "更看重拍照" not in answer

    assert len({tuple(sorted(mix)) for mix in mixes}) >= 4


def test_travel_planner_generalizes_by_scene_attributes_not_destination_products() -> None:
    cases = [
        ("chengdu", "我要去成都旅行，应该买什么", {"背包", "跑步鞋", "充电设备", "防晒", "咖啡"}, ["城市漫游", "多雨"]),
        ("zhangjiajie", "我要去张家界徒步，应该买什么", {"徒步鞋", "背包", "帽子", "充电设备", "坚果/零食"}, ["山地", "徒步"]),
        ("unknown_island", "我要去仙本那海岛玩，应该买什么", {"防晒", "速干T恤", "帽子", "充电设备", "功能饮料"}, ["海滨", "强紫外线"]),
    ]

    for key, query, expected_subcategories, expected_context_terms in cases:
        answer, products = _chat(f"business-travel-scene-generalize-{key}", query)
        actual = {product["sub_category"] for product in products}
        assert len(actual & expected_subcategories) >= 4
        assert "类目配额检索" in answer
        assert all(term in answer for term in expected_context_terms)


def test_broad_destination_provides_assumption_before_products() -> None:
    answer, products = _chat("business-travel-broad-japan", "我要去日本旅行，应该买什么")

    assert products
    assert "差异较大" in answer
    assert "先按城市观光" in answer
    assert {"背包", "充电设备", "防晒"} <= {product["sub_category"] for product in products}


def test_travel_bundle_uses_llm_need_slots_when_available() -> None:
    session_id = "business-llm-travel-plan"
    original = agent.llm.travel_need_plan

    async def fake_plan(message: str, session_id: str = "default") -> dict:
        return {
            "destination": "新疆",
            "scenario": "高原/干燥户外",
            "intro_focus": "高倍防晒、保湿修护、防风轻量、补能和充电",
            "slots": [
                {
                    "role": "高倍防晒",
                    "category": "美妆护肤",
                    "sub_category": "防晒",
                    "search_terms": "新疆 高原 干燥 高倍防晒 保湿 修护",
                    "reason": "新疆紫外线强且干燥",
                },
                {
                    "role": "防风轻量",
                    "category": "服饰运动",
                    "sub_category": None,
                    "search_terms": "新疆 自驾 防风 轻量 背包 帽子",
                    "reason": "适合长途户外移动",
                },
                {
                    "role": "出行充电",
                    "category": "数码电子",
                    "sub_category": "充电宝",
                    "search_terms": "长途 自驾 轻量 充电宝 快充",
                    "reason": "长途路上补电",
                },
            ],
        }

    agent.llm.travel_need_plan = fake_plan
    try:
        answer, products = _chat(session_id, "我要去新疆玩，应该买些什么")
    finally:
        agent.llm.travel_need_plan = original

    assert "新疆归因为" in answer
    assert "类目配额检索" in answer
    assert "高倍防晒" in answer
    assert products
    categories = {(product["category"], product["sub_category"]) for product in products}
    assert ("美妆护肤", "防晒") in categories
    assert any(category == "服饰运动" for category, _ in categories)
    assert any(category == "数码电子" for category, _ in categories)
    assert any(category == "食品饮料" for category, _ in categories)


def test_product_followups_answer_review_sku_source_and_after_sale_from_current_cards() -> None:
    session_id = "business-product-followups"
    answer, products = _chat(session_id, "我要看17pm")
    assert products and products[0]["product_id"] == "p_digital_003"

    sku_answer, sku_products = _chat(session_id, "第一款不同规格怎么选")
    assert "规格" in sku_answer or "颜色" in sku_answer or "存储" in sku_answer
    assert sku_products and sku_products[0]["product_id"] == "p_digital_003"

    source_answer, source_products = _chat(session_id, "第一款来源可靠吗")
    assert any(term in source_answer for term in ["来源", "商品库", "可信", "证据"])
    assert source_products and source_products[0]["product_id"] == "p_digital_003"

    after_sale_answer, after_sale_products = _chat(session_id, "第一款售后和保修怎么说")
    assert any(term in after_sale_answer for term in ["售后", "退换", "保修", "七天"])
    assert after_sale_products and after_sale_products[0]["product_id"] == "p_digital_003"

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.agent.grounding_guard import GroundingGuard
from app.api.routes import agent, sessions
from app.llm.schemas import ConversationPlan
from app.main import app
from app.models.schemas import LLMStatus

client = TestClient(app)


def _events(raw: str) -> list[dict]:
    events: list[dict] = []
    name: str | None = None
    for line in raw.splitlines():
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name:
            events.append({"event": name, "data": json.loads(line.removeprefix("data: "))})
            name = None
    return events


def _tokens(events: list[dict]) -> str:
    return "".join(e["data"] for e in events if e["event"] == "token")


def _products(events: list[dict]) -> list[dict]:
    return [item for e in events if e["event"] == "products" for item in e["data"]]


def _configured_status() -> LLMStatus:
    return LLMStatus(
        configured=True, provider="ark", model="mock", base_url=None,
        source="test", key_present=True, key_hint="mock",
    )


# ---- Pure-unit tests (no network) -------------------------------------------------

def test_sanitize_chat_strips_promo_and_price():
    g = GroundingGuard()
    assert g.sanitize_chat("这款挺适合你的。现在还有满减优惠哦！").strip() == "这款挺适合你的。"
    assert g.sanitize_chat("我帮你看看。它只要 99 元包邮。").strip() == "我帮你看看。"
    assert g.sanitize_chat("先领券立减50元！") is None
    assert g.sanitize_chat("今天累了就早点休息吧。") == "今天累了就早点休息吧。"


def test_plan_to_mode_mapping():
    fallback = agent.mode_router.route("x", has_last_products=False, has_pending_clarification=False, has_active_shopping_context=False)
    assert agent._plan_to_mode(ConversationPlan(intent="recommend", shopping_intent_level=3), fallback).mode == "shopping_assist"
    assert agent._plan_to_mode(ConversationPlan(intent="cart", shopping_intent_level=4), fallback).mode == "transaction"
    assert agent._plan_to_mode(ConversationPlan(intent="smalltalk", shopping_intent_level=0), fallback).mode == "general_chat"
    assert agent._plan_to_mode(ConversationPlan(intent="clarify", shopping_intent_level=1), fallback).mode == "weak_purchase_intent"
    # unknown intent defers to the deterministic fallback decision
    assert agent._plan_to_mode(ConversationPlan(intent="unknown"), fallback) is fallback


def test_high_confidence_route_explicit_vs_vague():
    def rule(msg):
        return agent.mode_router.route(msg, has_last_products=False, has_pending_clarification=False, has_active_shopping_context=False)

    session = sessions.get("hc-test")
    # explicit recommend with a concrete constraint -> fast path (skip planner)
    assert agent._high_confidence_route("推荐降噪耳机预算2000以内", rule("推荐降噪耳机预算2000以内"), session) is True
    # vague / emotional -> let the planner decide
    assert agent._high_confidence_route("最近压力有点大随便聊聊", rule("最近压力有点大随便聊聊"), session) is False


# ---- Agent-path tests with a mocked planner (no network) --------------------------

def test_planner_smalltalk_does_not_hard_sell():
    plan = ConversationPlan(intent="smalltalk", shopping_intent_level=0, reply="辛苦啦，先歇会儿放松一下~", rationale="情绪闲聊")
    with patch.object(agent.llm, "status", return_value=_configured_status()), \
         patch.object(agent.llm, "plan_turn", new=AsyncMock(return_value=plan)):
        response = client.post("/api/chat/stream", json={"session_id": "planner-chat", "message": "今天好累啊不想动"})
    events = _events(response.text)
    assert "辛苦啦" in _tokens(events)
    assert _products(events) == []  # chat turn must not surface product cards


def test_planner_clarify_uses_reply_and_asks():
    plan = ConversationPlan(intent="clarify", shopping_intent_level=2, reply="想帮你挑，先说下预算和更看重什么呀？", rationale="信息不足")
    with patch.object(agent.llm, "status", return_value=_configured_status()), \
         patch.object(agent.llm, "plan_turn", new=AsyncMock(return_value=plan)):
        response = client.post("/api/chat/stream", json={"session_id": "planner-clarify", "message": "想买点东西但没想好"})
    events = _events(response.text)
    assert "预算" in _tokens(events)
    done = [e["data"] for e in events if e["event"] == "done"][-1]
    assert done.get("needs_clarification") is True


def test_explicit_recommend_streams_prefix_and_products():
    # Offline (no key): planner is skipped, the answer stream is empty, so the
    # deterministic prefix + fallback + product cards must still be produced.
    response = client.post("/api/chat/stream", json={"session_id": "rec-offline", "message": "推荐适合油皮的防晒，250元以内"})
    events = _events(response.text)
    tokens = _tokens(events)
    assert tokens.startswith("以下信息来自本地商品库")
    assert len(_products(events)) >= 1

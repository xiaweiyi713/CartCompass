from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.api.routes import products
from app.agent.session_store import SessionStore
from app.observability import observability
from app.rag.product_repository import SearchConstraints


client = TestClient(app)


def _done_trace_id(text: str) -> str:
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line.removeprefix("data: "))
        if isinstance(payload, dict) and payload.get("trace_id"):
            return payload["trace_id"]
    raise AssertionError("trace_id not found")


def test_chat_trace_and_metrics_are_exposed() -> None:
    response = client.post(
        "/api/chat/stream",
        json={"session_id": "test-observability", "message": "推荐适合油皮的防晒，200元以内，不要含酒精"},
    )
    assert response.status_code == 200
    trace_id = _done_trace_id(response.text)

    trace_response = client.get(f"/api/traces/{trace_id}")
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["trace_id"] == trace_id
    assert trace["status"] == "ok"
    assert any(step["name"] == "constraint_parser" for step in trace["steps"])
    assert any(step["name"] == "retrieval" for step in trace["steps"])

    metrics_response = client.get("/api/metrics")
    assert metrics_response.status_code == 200
    metrics = metrics_response.json()
    assert int(metrics["product_stats"]["商品总数"]) >= 100
    assert "derived_metrics" in metrics
    assert "retrieval_cache_hit_rate" in metrics["derived_metrics"]
    assert metrics["counters"]["chat_requests"] >= 1
    assert "chat_latency_ms" in metrics["latencies"]


def test_admin_metrics_dashboard_renders_html() -> None:
    response = client.get("/admin/metrics")
    assert response.status_code == 200
    assert "ShopGuide 评测与可观测性 Dashboard" in response.text
    assert "商品总数" in response.text
    assert "retrieval cache hit rate" in response.text


def test_retrieval_cache_records_hit_rate_metric() -> None:
    before_hits = observability.counters.get("retrieval_cache_hits", 0)
    constraints = SearchConstraints(category="数码电子", sub_category="充电设备")

    first = products.search("pytest unique cache anker fast charging", constraints, limit=4)
    second = products.search("pytest unique cache anker fast charging", constraints, limit=4)

    assert [product.product_id for product in first] == [product.product_id for product in second]
    assert observability.counters["retrieval_cache_hits"] >= before_hits + 1
    snapshot = observability.snapshot({"商品总数": 1})
    assert snapshot["derived_metrics"]["retrieval_cache_hit_rate"] != "n/a"


def test_session_store_prunes_ttl_and_lru(monkeypatch) -> None:
    now = 1_000.0
    monkeypatch.setattr("app.agent.session_store.time.time", lambda: now)
    store = SessionStore(ttl_seconds=10, max_entries=2)

    first = store.get("first")
    store.get("second")
    store.get("first")
    store.get("third")

    assert store.size() == 2
    assert store.get("first") is first

    now = 1_020.0
    assert store.size() == 0


def test_product_repository_prefilters_candidates_in_sql() -> None:
    rows = products._candidate_rows(SearchConstraints(category="数码电子", max_price=1200))

    assert rows
    assert all(row["category"] == "数码电子" for row in rows)
    assert all(row["base_price"] <= 1200 for row in rows)
    assert len(rows) < len(products.all())

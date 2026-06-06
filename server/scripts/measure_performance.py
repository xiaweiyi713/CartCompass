from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.observability import observability  # noqa: E402


DEFAULT_QUERIES = [
    "推荐适合油皮的防晒，200元以内，不要含酒精",
    "推荐几款手机，预算9000，拍照好一点",
    "我下周去三亚旅行，预算1000，应该买什么？",
    "推荐降噪耳机，预算800，通勤用，续航要好",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure reproducible CartCompass chat performance.")
    parser.add_argument("--repeat", type=int, default=2, help="Run each query this many times. Repeat >1 demonstrates cache hit rate.")
    parser.add_argument("--output", type=Path, default=Path("server/evaluation/output/performance_report.json"))
    parser.add_argument("--query", action="append", default=[], help="Override default query set. Can be repeated.")
    args = parser.parse_args()

    queries = args.query or DEFAULT_QUERIES
    client = TestClient(app)
    runs: list[dict[str, Any]] = []
    for round_index in range(max(1, args.repeat)):
        for query in queries:
            runs.append(_measure_turn(client, query, round_index + 1))

    latencies = [run["total_latency_ms"] for run in runs]
    first_tokens = [run["first_token_latency_ms"] for run in runs if run["first_token_latency_ms"] is not None]
    snapshot = observability.snapshot({"source": "measure_performance.py"})
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "queries": queries,
        "repeat": max(1, args.repeat),
        "summary": {
            "turns": len(runs),
            "total_latency_p50_ms": _percentile(latencies, 50),
            "total_latency_p95_ms": _percentile(latencies, 95),
            "first_token_p50_ms": _percentile(first_tokens, 50),
            "first_token_p95_ms": _percentile(first_tokens, 95),
            "retrieval_cache_hit_rate": snapshot["derived_metrics"].get("retrieval_cache_hit_rate"),
            "recommendation_cache_hit_rate": snapshot["derived_metrics"].get("recommendation_cache_hit_rate"),
        },
        "runs": runs,
        "metrics_snapshot": snapshot,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_json={args.output.resolve()}")


def _measure_turn(client: TestClient, query: str, round_index: int) -> dict[str, Any]:
    session_id = f"perf-{uuid.uuid4().hex[:8]}"
    started = time.perf_counter()
    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": query})
    elapsed_ms = (time.perf_counter() - started) * 1000
    events = _parse_sse(response.text)
    trace_id = None
    products = []
    for event in events:
        if event["event"] == "products" and isinstance(event["data"], list):
            products.extend(event["data"])
        if event["event"] == "done" and isinstance(event["data"], dict):
            trace_id = event["data"].get("trace_id")
    trace = observability.get_trace(trace_id) if trace_id else None
    return {
        "round": round_index,
        "query": query,
        "status_code": response.status_code,
        "total_latency_ms": round(elapsed_ms, 2),
        "first_token_latency_ms": _trace_step_payload(trace, "sse_first_token", "latency_ms"),
        "product_count": len(products),
        "trace_id": trace_id,
        "retrieval_stack": _trace_step_payload(trace, "retrieval", "retrieval_stack"),
        "cache_hit": _trace_step_payload(trace, "retrieval", "cache_hit"),
    }


def _parse_sse(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_name: str | None = None
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: ") and event_name:
            events.append(
                {
                    "event": event_name,
                    "data": json.loads(line.removeprefix("data: ")),
                }
            )
            event_name = None
    return events


def _trace_step_payload(trace: dict[str, Any] | None, step_name: str, key: str) -> Any:
    if not trace:
        return None
    for step in trace.get("steps", []):
        if step.get("name") != step_name:
            continue
        payload = step.get("payload") if isinstance(step, dict) else None
        if isinstance(payload, dict) and key in payload:
            return payload[key]
    return None


def _percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    ordered = sorted(values)
    return round(statistics.quantiles(ordered, n=100, method="inclusive")[percent - 1], 2)


if __name__ == "__main__":
    main()

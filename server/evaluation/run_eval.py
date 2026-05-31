from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from report_generator import render_report  # noqa: E402

from app.main import app  # noqa: E402


CASES_DIR = Path(__file__).resolve().parent / "cases"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def run_evaluation(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    client = TestClient(app)
    raw_cases = _load_cases()
    case_results = [_run_case(client, case) for case in raw_cases]
    metrics = _metrics(case_results)
    results = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
        "cases": case_results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation_report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "evaluation_report.html").write_text(render_report(results), encoding="utf-8")
    return results


def _load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(CASES_DIR.glob("*.json")):
        cases.extend(json.loads(path.read_text(encoding="utf-8")))
    return cases


def _run_case(client: TestClient, case: dict[str, Any]) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        if case["type"] == "chat":
            result = _run_chat_case(client, case)
        elif case["type"] == "multi_turn":
            result = _run_multi_turn_case(client, case)
        elif case["type"] == "visual_search":
            result = _run_visual_case(client, case)
        elif case["type"] == "cart":
            result = _run_cart_case(client, case)
        else:
            result = {"passed": False, "details": {"error": f"unknown case type {case['type']}"}}
    except Exception as exc:  # noqa: BLE001 - eval report should preserve unexpected failures.
        result = {"passed": False, "details": {"error": str(exc)}}
    result["id"] = case["id"]
    result["type"] = case["type"]
    result["latency_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
    return result


def _run_chat_case(client: TestClient, case: dict[str, Any]) -> dict[str, Any]:
    session_id = f"eval-{case['id']}-{uuid.uuid4().hex[:6]}"
    if case.get("followup"):
        _chat(client, session_id, case["query"])
        response = _chat(client, session_id, case["followup"])
    else:
        response = _chat(client, session_id, case["query"])
    return _evaluate_chat_response(case, response)


def _run_multi_turn_case(client: TestClient, case: dict[str, Any]) -> dict[str, Any]:
    session_id = f"eval-{case['id']}-{uuid.uuid4().hex[:6]}"
    turn_results = []
    passed = True
    final_response: dict[str, Any] = {"product_ids": []}
    for turn in case["turns"]:
        final_response = _chat(client, session_id, turn["query"])
        turn_result = _evaluate_chat_response(turn, final_response)
        turn_results.append(turn_result)
        passed = passed and turn_result["passed"]
    return {
        "passed": passed,
        "product_ids": final_response.get("product_ids", []),
        "details": {"turns": turn_results},
        "metrics": _chat_metric_flags(case["turns"][-1], final_response),
    }


def _run_visual_case(client: TestClient, case: dict[str, Any]) -> dict[str, Any]:
    path = ROOT / case["image_path"]
    params = {"query": case.get("query", "")} if case.get("query") else None
    with path.open("rb") as image:
        response = client.post(
            "/api/image_search",
            params=params,
            files={"file": (path.name, image, "image/jpeg")},
        )
    payload = response.json()
    products = payload.get("products", [])
    product_ids = [product["product_id"] for product in products]
    k = int(case.get("k", 5))
    expected = set(case.get("expected_topk", []))
    passed = response.status_code == 200 and bool(expected.intersection(product_ids[:k]))
    return {
        "passed": passed,
        "product_ids": product_ids,
        "details": {"expected_topk": list(expected), "k": k, "trace_id": payload.get("trace_id")},
        "metrics": {"visual_topk_hit": passed},
    }


def _run_cart_case(client: TestClient, case: dict[str, Any]) -> dict[str, Any]:
    session_id = f"eval-cart-{uuid.uuid4().hex[:6]}"
    add_response = client.post(
        "/api/cart/add",
        json={
            "session_id": session_id,
            "product_id": case["product_id"],
            "sku_id": case.get("sku_id"),
            "quantity": case.get("quantity", 1),
        },
    )
    checkout_response = client.post(
        "/api/cart/checkout",
        json={"session_id": session_id, "address": "自动化评测地址"},
    )
    passed = add_response.status_code == 200 and checkout_response.status_code == 200
    checkout_payload = checkout_response.json() if checkout_response.status_code == 200 else {}
    has_recommendations = bool(checkout_payload.get("post_purchase_recommendations"))
    return {
        "passed": passed,
        "product_ids": [case["product_id"]],
        "details": {
            "add_status": add_response.status_code,
            "checkout_status": checkout_response.status_code,
            "order_id": checkout_payload.get("order_id"),
            "post_purchase_recommendations": [item.get("product_id") for item in checkout_payload.get("post_purchase_recommendations", [])],
        },
        "metrics": {"cart_success": passed, "post_purchase_recommendation_ok": has_recommendations},
    }


def _chat(client: TestClient, session_id: str, message: str) -> dict[str, Any]:
    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": message})
    events = _parse_sse(response.text)
    products = [item for event in events if event["event"] == "products" for item in event["data"]]
    plans = [event["data"] for event in events if event["event"] == "plan"]
    tokens = "".join(event["data"] for event in events if event["event"] == "token")
    done_events = [event["data"] for event in events if event["event"] == "done"]
    product_ids = [product.get("product_id") for product in products if isinstance(product, dict)]
    return {
        "status_code": response.status_code,
        "events": events,
        "text": tokens,
        "raw": response.text,
        "products": products,
        "plans": plans,
        "product_ids": product_ids,
        "done": done_events[-1] if done_events else {},
    }


def _evaluate_chat_response(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    flags = _chat_metric_flags(case, response)
    checks = {
        "status_ok": response["status_code"] == 200,
        "min_products": len(response["product_ids"]) >= int(case.get("expected_min_products", 0)),
        "expected_text": all(term in response["text"] or term in response["raw"] for term in case.get("expected_text_contains", [])),
        "expected_products": _expected_products_hit(case, response["product_ids"]),
        "clarification": _clarification_matches(case, response),
        "must_not_contain": all(term not in response["raw"] for term in case.get("must_not_contain", [])),
        "must_not_brand": _must_not_brand(case, response["products"]),
        "expected_category": _expected_category(case, response["products"]),
        "plan": _plan_matches(case, response),
    }
    passed = all(checks.values())
    return {
        "passed": passed,
        "product_ids": response["product_ids"],
        "details": {"checks": checks, "text": response["text"][:260], "trace_id": response["done"].get("trace_id")},
        "metrics": flags,
    }


def _chat_metric_flags(case: dict[str, Any], response: dict[str, Any]) -> dict[str, bool]:
    product_ids = response.get("product_ids", [])
    return {
        "top3_hit": _expected_products_hit(case, product_ids[:3]) if case.get("expected_product_ids") else True,
        "negative_filter_ok": _must_not_brand(case, response.get("products", [])) if case.get("must_not_brand") else True,
        "clarification_ok": _clarification_matches(case, response) if "expect_clarification" in case else True,
        "plan_ok": _plan_matches(case, response) if "expect_plan" in case else True,
    }


def _parse_sse(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_name: str | None = None
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: ") and event_name:
            events.append({"event": event_name, "data": json.loads(line.removeprefix("data: "))})
            event_name = None
    return events


def _expected_products_hit(case: dict[str, Any], product_ids: list[str]) -> bool:
    expected = set(case.get("expected_product_ids", []))
    return not expected or bool(expected.intersection(product_ids))


def _clarification_matches(case: dict[str, Any], response: dict[str, Any]) -> bool:
    if "expect_clarification" not in case:
        return True
    return bool(response["done"].get("needs_clarification")) is bool(case["expect_clarification"])


def _must_not_brand(case: dict[str, Any], products: list[dict[str, Any]]) -> bool:
    excluded = [brand.lower() for brand in case.get("must_not_brand", [])]
    if not excluded:
        return True
    return all(
        not any(brand in str(product.get("brand", "")).lower() for brand in excluded)
        for product in products
    )


def _expected_category(case: dict[str, Any], products: list[dict[str, Any]]) -> bool:
    expected = case.get("expected_category")
    if not expected:
        return True
    return bool(products) and all(product.get("category") == expected for product in products)


def _plan_matches(case: dict[str, Any], response: dict[str, Any]) -> bool:
    if "expect_plan" not in case:
        return True
    plans = response.get("plans", [])
    if not case["expect_plan"]:
        return not plans
    return bool(plans) and len(plans[-1].get("items", [])) >= 2 and plans[-1].get("total_price", 0) > 0


def _metrics(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    metric_flags: dict[str, list[bool]] = {
        "top3_hit_rate": [],
        "negative_filter_accuracy": [],
        "clarification_accuracy": [],
        "cart_success_rate": [],
        "visual_topk_hit_rate": [],
        "budget_plan_success_rate": [],
        "post_purchase_recommendation_rate": [],
    }
    for case in case_results:
        for key, value in (case.get("metrics") or {}).items():
            target_key = _metric_key(key)
            if target_key in metric_flags:
                metric_flags[target_key].append(bool(value))
    latencies = [case["latency_ms"] for case in case_results]
    return {
        "total_cases": len(case_results),
        "passed_cases": sum(1 for case in case_results if case["passed"]),
        "case_pass_rate": _rate([case["passed"] for case in case_results]),
        "top3_hit_rate": _rate(metric_flags["top3_hit_rate"]),
        "negative_filter_accuracy": _rate(metric_flags["negative_filter_accuracy"]),
        "clarification_accuracy": _rate(metric_flags["clarification_accuracy"]),
        "cart_success_rate": _rate(metric_flags["cart_success_rate"]),
        "visual_topk_hit_rate": _rate(metric_flags["visual_topk_hit_rate"]),
        "budget_plan_success_rate": _rate(metric_flags["budget_plan_success_rate"]),
        "post_purchase_recommendation_rate": _rate(metric_flags["post_purchase_recommendation_rate"]),
        "avg_latency_ms": statistics.fmean(latencies) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 95),
    }


def _metric_key(key: str) -> str:
    mapping = {
        "top3_hit": "top3_hit_rate",
        "negative_filter_ok": "negative_filter_accuracy",
        "clarification_ok": "clarification_accuracy",
        "cart_success": "cart_success_rate",
        "visual_topk_hit": "visual_topk_hit_rate",
        "plan_ok": "budget_plan_success_rate",
        "post_purchase_recommendation_ok": "post_purchase_recommendation_rate",
    }
    return mapping.get(key, key)


def _rate(values: list[bool]) -> float:
    if not values:
        return 1.0
    return sum(1 for value in values if value) / len(values)


def _percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(sorted(values), n=100, method="inclusive")[percent - 1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ShopGuide agent capability evaluation.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    results = run_evaluation(args.output_dir)
    print(json.dumps(results["metrics"], ensure_ascii=False, indent=2))
    print(f"report_json={args.output_dir / 'evaluation_report.json'}")
    print(f"report_html={args.output_dir / 'evaluation_report.html'}")


if __name__ == "__main__":
    main()

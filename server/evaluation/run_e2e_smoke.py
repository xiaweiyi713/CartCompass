from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.routes import agent  # noqa: E402
from app.main import app  # noqa: E402
from app.rag.product_repository import ProductRepository  # noqa: E402


CASES_PATH = Path(__file__).resolve().parent / "cases" / "e2e_agent_smoke_cases.json"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "e2e_smoke"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run attachment-derived ShopGuide E2E smoke cases.")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case", action="append", default=[], help="Run only the given case id. Can be repeated.")
    parser.add_argument("--case-timeout", type=int, default=45)
    args = parser.parse_args()
    results = run(args.cases, args.output_dir, only=set(args.case), case_timeout=args.case_timeout)
    print(json.dumps(results["metrics"], ensure_ascii=False, indent=2))
    failed = [case for case in results["cases"] if not case["passed"]]
    for case in failed:
        print(f"\nFAILED {case['id']} {case['name']}")
        for item in case["failures"]:
            print(f"- {item}")
    print(f"report_json={args.output_dir / 'e2e_smoke_report.json'}")


def run(cases_path: Path, output_dir: Path, only: set[str] | None = None, case_timeout: int = 45) -> dict[str, Any]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if only:
        cases = [case for case in cases if case["id"] in only]
    client = TestClient(app)
    db = ProductRepository()
    known_ids = {product.product_id for product in db.all()}
    results = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']} {case.get('name', '')}", flush=True)
        results.append(_run_case_with_timeout(client, db, known_ids, case, case_timeout))
    active = [case for case in results if not case.get("skipped")]
    metrics = {
        "total_cases": len(results),
        "skipped_cases": sum(1 for case in results if case.get("skipped")),
        "passed_cases": sum(1 for case in active if case["passed"]),
        "case_pass_rate": (sum(1 for case in active if case["passed"]) / len(active)) if active else 1.0,
        "avg_latency_ms": round(sum(case["latency_ms"] for case in active) / len(active), 2) if active else 0.0,
        "max_latency_ms": max((case["latency_ms"] for case in active), default=0.0),
    }
    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "metrics": metrics, "cases": results}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "e2e_smoke_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


class CaseTimeoutError(Exception):
    pass


def _run_case_with_timeout(client: TestClient, db: ProductRepository, known_ids: set[str], case: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    def _timeout_handler(signum, frame):  # noqa: ANN001
        raise CaseTimeoutError(f"case exceeded {timeout_seconds}s")

    previous_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(max(1, timeout_seconds))
    try:
        return _run_case(client, db, known_ids, case)
    except CaseTimeoutError as exc:
        return {
            "id": case["id"],
            "name": case.get("name", case["id"]),
            "passed": False,
            "latency_ms": float(timeout_seconds * 1000),
            "failures": [str(exc)],
            "turns": [],
        }
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def _run_case(client: TestClient, db: ProductRepository, known_ids: set[str], case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    session_id = f"e2e-{case['id']}-{uuid.uuid4().hex[:6]}"
    failures: list[str] = []
    responses: list[dict[str, Any]] = []
    original_weather_lookup = agent.weather.lookup
    configured_model = False
    try:
        setup = case.get("test_setup") or {}
        if setup.get("force_weather_provider_failure"):
            async def failing_lookup(location: str, days: int = 7):  # noqa: ANN001
                return None

            agent.weather.lookup = failing_lookup  # type: ignore[method-assign]
        if setup.get("provider") == "disabled":
            configured_model = True
            client.post("/api/llm/config", json={"session_id": session_id, "provider": "disabled", "temporary": True})
        if setup.get("cart_has_items"):
            client.post("/api/cart/add", json={"session_id": session_id, "product_id": "p_digital_001", "quantity": 1})

        previous_first_price: float | None = None
        for turn in case["turns"]:
            response = _run_turn(client, session_id, turn)
            responses.append(response)
            _assert_turn(turn, response, db, known_ids, failures, previous_first_price)
            if response["products"]:
                previous_first_price = float(response["products"][0].get("base_price") or 0)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"case raised {type(exc).__name__}: {exc}")
    finally:
        agent.weather.lookup = original_weather_lookup  # type: ignore[method-assign]
        if configured_model:
            client.delete(f"/api/llm/config/{session_id}")
    return {
        "id": case["id"],
        "name": case.get("name", case["id"]),
        "passed": not failures,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "failures": failures,
        "turns": [
            {
                "query": item.get("query") or item.get("type"),
                "mode": item.get("mode"),
                "text": item.get("text", "")[:320],
                "product_ids": [product.get("product_id") for product in item.get("products", [])],
                "cart_items": len((item.get("cart") or {}).get("items", [])) if item.get("cart") else None,
                "trace_id": (item.get("done") or {}).get("trace_id"),
            }
            for item in responses
        ],
    }


def _run_turn(client: TestClient, session_id: str, turn: dict[str, Any]) -> dict[str, Any]:
    if turn.get("type") == "image":
        path = ROOT / turn["path"]
        with path.open("rb") as image:
            response = client.post("/api/image_search", params={"query": turn.get("query", "")}, files={"file": (path.name, image, "image/jpeg")})
        payload = response.json()
        return {
            "status_code": response.status_code,
            "mode": "visual_search",
            "text": payload.get("summary", ""),
            "products": payload.get("products", []),
            "events": [],
            "done": {"ok": response.status_code == 200, "mode": "visual_search", "trace_id": payload.get("trace_id")},
        }
    if turn.get("type") == "mock_payment":
        created = client.post("/api/checkout/session", json={"session_id": session_id, "address": "自动化评测地址"})
        if created.status_code != 200:
            return {"status_code": created.status_code, "mode": "checkout", "text": created.text, "products": [], "events": [], "done": {}, "checkout": created.json()}
        checkout_id = created.json()["checkout_session_id"]
        paid = client.post(f"/api/checkout/{checkout_id}/pay/mock", json={"outcome": turn.get("outcome", "success")})
        payload = paid.json()
        cart_after = client.get(f"/api/cart/{session_id}")
        return {
            "status_code": paid.status_code,
            "mode": "checkout",
            "text": json.dumps(payload, ensure_ascii=False),
            "products": [],
            "events": [],
            "done": {"mode": "checkout"},
            "payment": payload,
            "cart_after": cart_after.json() if cart_after.status_code == 200 else None,
        }
    if turn.get("type") == "checkout_review":
        created = client.post("/api/checkout/session", json={"session_id": session_id, "address": "自动化评测地址"})
        payload = created.json()
        return {
            "status_code": created.status_code,
            "mode": "checkout",
            "text": json.dumps(payload, ensure_ascii=False),
            "products": [],
            "events": [],
            "done": {"mode": "checkout"},
            "checkout": payload,
        }
    return _chat(client, session_id, turn["query"])


def _chat(client: TestClient, session_id: str, message: str) -> dict[str, Any]:
    response = client.post("/api/chat/stream", json={"session_id": session_id, "message": message})
    events = _parse_sse(response.text)
    products = [item for event in events if event["event"] == "products" and isinstance(event["data"], list) for item in event["data"]]
    text = "".join(str(event["data"]) for event in events if event["event"] == "token")
    done = next((event["data"] for event in reversed(events) if event["event"] == "done"), {})
    mode = done.get("mode") if isinstance(done, dict) else None
    cart = next((event["data"] for event in reversed(events) if event["event"] == "cart"), None)
    return {
        "status_code": response.status_code,
        "mode": mode,
        "text": text,
        "raw": response.text,
        "events": events,
        "products": products,
        "plans": [event["data"] for event in events if event["event"] == "plan"],
        "weather": [event["data"] for event in events if event["event"] == "weather"],
        "profile": [event["data"] for event in events if event["event"] == "profile"],
        "cart": cart,
        "done": done if isinstance(done, dict) else {},
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


def _assert_turn(
    expected: dict[str, Any],
    response: dict[str, Any],
    db: ProductRepository,
    known_ids: set[str],
    failures: list[str],
    previous_first_price: float | None,
) -> None:
    prefix = expected.get("query") or expected.get("type")
    if response["status_code"] >= 400:
        failures.append(f"{prefix}: HTTP {response['status_code']}")
    mode = response.get("mode")
    if expected.get("expect_mode") and mode != expected["expect_mode"]:
        failures.append(f"{prefix}: mode expected {expected['expect_mode']}, got {mode}")
    if expected.get("expect_mode_any") and mode not in expected["expect_mode_any"]:
        failures.append(f"{prefix}: mode expected one of {expected['expect_mode_any']}, got {mode}")
    if "expect_products" in expected:
        has_products = bool(response["products"])
        if has_products is not bool(expected["expect_products"]):
            failures.append(f"{prefix}: products expected {expected['expect_products']}, got {len(response['products'])}")
    if len(response["products"]) < int(expected.get("expected_min_products", 0)):
        failures.append(f"{prefix}: expected at least {expected['expected_min_products']} products, got {len(response['products'])}")
    if expected.get("expect_products_or_clarify") and not response["products"] and not response.get("done", {}).get("needs_clarification"):
        failures.append(f"{prefix}: expected products or clarification")
    if expected.get("expect_clarification") and not response.get("done", {}).get("needs_clarification"):
        failures.append(f"{prefix}: expected clarification")
    if expected.get("expect_plan") and not response.get("plans"):
        failures.append(f"{prefix}: expected shopping plan event")
    if expected.get("expect_weather") is False and response.get("weather"):
        failures.append(f"{prefix}: expected no weather event")
    if expected.get("expect_weather") is True and not response.get("weather"):
        failures.append(f"{prefix}: expected weather event")
    if expected.get("expect_profile") and not response.get("profile"):
        failures.append(f"{prefix}: expected profile event")
    if expected.get("expect_cart_items_min") is not None:
        items = (response.get("cart") or {}).get("items", [])
        if len(items) < int(expected["expect_cart_items_min"]):
            failures.append(f"{prefix}: expected cart items >= {expected['expect_cart_items_min']}, got {len(items)}")
    if expected.get("expect_distinct_sku_lines_min") is not None:
        items = (response.get("cart") or {}).get("items", [])
        distinct = {
            (
                (item.get("product") or {}).get("product_id") or item.get("product_id"),
                (item.get("selected_sku") or {}).get("sku_id") or item.get("sku_id"),
            )
            for item in items
        }
        if len(distinct) < int(expected["expect_distinct_sku_lines_min"]):
            failures.append(f"{prefix}: expected distinct sku lines >= {expected['expect_distinct_sku_lines_min']}, got {len(distinct)}")
    if expected.get("expect_order_status"):
        status = (response.get("payment") or {}).get("status")
        if str(status).lower() != str(expected["expect_order_status"]).lower():
            failures.append(f"{prefix}: expected payment status {expected['expect_order_status']}, got {status}")
    if expected.get("expect_payment_status"):
        status = (response.get("payment") or {}).get("payment_status")
        if str(status).lower() != str(expected["expect_payment_status"]).lower():
            failures.append(f"{prefix}: expected payment_status {expected['expect_payment_status']}, got {status}")
    if expected.get("expect_cart_quantity") is not None:
        items = (response.get("cart") or {}).get("items", [])
        total_quantity = sum(int(item.get("quantity") or 0) for item in items)
        if total_quantity != int(expected["expect_cart_quantity"]):
            failures.append(f"{prefix}: expected cart quantity {expected['expect_cart_quantity']}, got {total_quantity}")
    if expected.get("expect_cart_empty_after_payment"):
        items = (response.get("cart_after") or {}).get("items", [])
        if items:
            failures.append(f"{prefix}: expected empty cart after payment, got {len(items)} items")
    if expected.get("expect_cart_not_empty_after_payment"):
        items = (response.get("cart_after") or {}).get("items", [])
        if not items:
            failures.append(f"{prefix}: expected cart to remain after payment failure")
    if expected.get("expect_checkout_review"):
        review = (response.get("checkout") or {}).get("review") or []
        if not review:
            failures.append(f"{prefix}: expected checkout review")
    if expected.get("expect_similarity_score"):
        scored = [
            product
            for product in response.get("products", [])
            if int(product.get("match_score") or 0) > 0 or product.get("match_reasons")
        ]
        if not scored:
            failures.append(f"{prefix}: expected visual similarity score or match reasons")
    _assert_text(expected, response, failures, prefix)
    _assert_products(expected, response, db, known_ids, failures, prefix, previous_first_price)


def _assert_text(expected: dict[str, Any], response: dict[str, Any], failures: list[str], prefix: str) -> None:
    text = response.get("text", "") + "\n" + response.get("raw", "")
    if expected.get("must_contain_any") and not any(term in text for term in expected["must_contain_any"]):
        failures.append(f"{prefix}: expected text to contain any of {expected['must_contain_any']}")
    for term in expected.get("must_not_contain", []):
        if term in text:
            failures.append(f"{prefix}: text must not contain {term!r}")


def _assert_products(
    expected: dict[str, Any],
    response: dict[str, Any],
    db: ProductRepository,
    known_ids: set[str],
    failures: list[str],
    prefix: str,
    previous_first_price: float | None,
) -> None:
    products = response.get("products") or []
    scoped_products = products[: int(expected["expected_top_k"])] if expected.get("expected_top_k") else products
    if expected.get("assert_all_product_ids_exist", True):
        unknown = [product.get("product_id") for product in products if product.get("product_id") not in known_ids]
        if unknown:
            failures.append(f"{prefix}: product cards not in DB: {unknown}")
    if expected.get("expected_category") and scoped_products:
        bad = [product.get("product_id") for product in scoped_products if product.get("category") != expected["expected_category"]]
        if bad:
            failures.append(f"{prefix}: products outside category {expected['expected_category']}: {bad}")
    if expected.get("expected_sub_category") and scoped_products:
        bad = [product.get("product_id") for product in scoped_products if product.get("sub_category") != expected["expected_sub_category"]]
        if bad:
            failures.append(f"{prefix}: products outside sub_category {expected['expected_sub_category']}: {bad}")
    if expected.get("max_price") is not None and scoped_products:
        max_price = float(expected["max_price"])
        bad = [f"{product.get('product_id')}={product.get('base_price')}" for product in scoped_products if float(product.get("base_price") or 0) > max_price]
        if bad:
            failures.append(f"{prefix}: products over max price {max_price}: {bad}")
    if expected.get("expect_first_price_min") is not None and products:
        first_price = float(products[0].get("base_price") or 0)
        min_price = float(expected["expect_first_price_min"])
        if first_price < min_price:
            failures.append(f"{prefix}: expected first product price >= {min_price}, got {first_price}")
    for brand in expected.get("must_not_brand", []):
        bad = [product.get("product_id") for product in scoped_products if brand.lower() in str(product.get("brand", "")).lower()]
        if bad:
            failures.append(f"{prefix}: excluded brand {brand} appeared in {bad}")
    if expected.get("expect_cheaper_than_previous_first") and previous_first_price and products:
        first_price = float(products[0].get("base_price") or 0)
        if first_price >= previous_first_price:
            failures.append(f"{prefix}: first alternative {first_price} is not cheaper than previous {previous_first_price}")
    if expected.get("expect_premium_than_previous_first") and previous_first_price and products:
        first_price = float(products[0].get("base_price") or 0)
        if first_price <= previous_first_price:
            failures.append(f"{prefix}: first alternative {first_price} is not premium over previous {previous_first_price}")


if __name__ == "__main__":
    main()

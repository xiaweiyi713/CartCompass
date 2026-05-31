from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


BLOCKED_TITLE_TERMS = (
    "gift card",
    "e-gift",
    "digital gift",
    "patch",
    "sticker",
    "replacement",
    "refurbished",
    "shoe laces",
)
BLOCKED_IMAGE_TERMS = ("no-image", "logo-seo", "placeholder", "venia-static")
MAX_PRICE_CNY = 15000.0
MIN_DESCRIPTION_LENGTH = 24


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter cleaned crawler products before SQLite merge.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    products = load_products(args.input)
    curated, rejected = curate(products)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(curated, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "input_count": len(products),
        "curated_count": len(curated),
        "rejected_count": len(rejected),
        "rejected_reasons": rejected,
        "category_counts": category_counts(curated),
        "source_counts": source_counts(curated),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rejected_reasons"}, ensure_ascii=False, indent=2))


def load_products(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("input must be a JSON list")
    return data


def curate(products: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    curated: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for product in products:
        reason = rejection_reason(product, seen_urls, seen_titles)
        if reason:
            rejected.append(
                {
                    "product_id": str(product.get("product_id", "")),
                    "title": str(product.get("title", "")),
                    "reason": reason,
                }
            )
            continue
        seen_urls.add(str(product.get("product_url", "")))
        seen_titles.add(normalized_title(product))
        curated.append(product)
    return curated, rejected


def rejection_reason(product: dict[str, Any], seen_urls: set[str], seen_titles: set[str]) -> str:
    title = normalized_title(product)
    if not title:
        return "missing title"
    if title in seen_titles:
        return "duplicate title"
    if any(term in title for term in BLOCKED_TITLE_TERMS):
        return "not useful for recommendation"
    try:
        price = float(product.get("base_price", 0))
    except (TypeError, ValueError):
        return "invalid price"
    if price <= 0:
        return "missing price"
    if price > MAX_PRICE_CNY:
        return "unrealistic price"
    image_url = str(product.get("image_url", "")).lower()
    if not image_url or any(term in image_url for term in BLOCKED_IMAGE_TERMS):
        return "invalid image"
    description = str(product.get("rag_knowledge", {}).get("marketing_description", ""))
    if len(description) < MIN_DESCRIPTION_LENGTH:
        return "description too short"
    product_url = str(product.get("product_url", ""))
    if product_url and product_url in seen_urls:
        return "duplicate url"
    if not _valid_skus(product.get("skus")):
        return "invalid skus"
    return ""


def normalized_title(product: dict[str, Any]) -> str:
    return " ".join(str(product.get("title", "")).lower().split())


def _valid_skus(skus: Any) -> bool:
    if not isinstance(skus, list) or not skus:
        return False
    for sku in skus:
        if not isinstance(sku, dict) or not sku.get("sku_id"):
            return False
        try:
            float(sku.get("price"))
        except (TypeError, ValueError):
            return False
    return True


def category_counts(products: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for product in products:
        category = str(product.get("category", ""))
        counts[category] = counts.get(category, 0) + 1
    return counts


def source_counts(products: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for product in products:
        skus = product.get("skus") or []
        source = "unknown"
        if skus and isinstance(skus[0], dict):
            source = str((skus[0].get("properties") or {}).get("来源", "unknown"))
        counts[source] = counts.get(source, 0) + 1
    return counts


if __name__ == "__main__":
    main()

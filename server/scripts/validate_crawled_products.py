from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import DB_PATH, PRODUCT_IMAGE_DIR, SERVER_DIR


REQUIRED_FIELDS = {
    "product_id",
    "title",
    "brand",
    "category",
    "sub_category",
    "base_price",
    "image_url",
    "skus",
    "rag_knowledge",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate crawled product files and optional SQLite import status.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=sorted((SERVER_DIR / "data_pipeline" / "output").glob("*/products_clean.json")),
        help="products_clean.json files to validate. Defaults to every output/*/products_clean.json.",
    )
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    args = parser.parse_args()

    failures: list[str] = []
    products: list[dict[str, Any]] = []

    for path in args.paths:
        loaded = load_products(path, failures)
        products.extend(loaded)
        print(f"{path}: {len(loaded)} products")

    failures.extend(validate_products(products))
    if args.db_path.exists():
        failures.extend(validate_db(products, args.db_path))
    else:
        failures.append(f"SQLite database not found: {args.db_path}")

    category_counts = Counter(product.get("category", "") for product in products)
    print(f"total clean products: {len(products)}")
    print(f"categories: {dict(category_counts)}")

    if failures:
        print("\nValidation failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("Validation passed.")


def load_products(path: Path, failures: list[str]) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        failures.append(f"{path}: cannot read file ({exc})")
        return []
    except json.JSONDecodeError as exc:
        failures.append(f"{path}: invalid JSON ({exc})")
        return []

    if not isinstance(data, list):
        failures.append(f"{path}: expected a JSON list")
        return []
    if not all(isinstance(item, dict) for item in data):
        failures.append(f"{path}: every product must be an object")
        return []
    return data


def validate_products(products: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    ids = [str(product.get("product_id", "")) for product in products]
    for product_id, count in Counter(ids).items():
        if product_id and count > 1:
            failures.append(f"duplicate product_id: {product_id}")

    for product in products:
        product_id = str(product.get("product_id", "<missing-id>"))
        missing = sorted(field for field in REQUIRED_FIELDS if product.get(field) in (None, "", []))
        if missing:
            failures.append(f"{product_id}: missing required fields {missing}")
        try:
            price = float(product.get("base_price", 0))
            if price <= 0:
                failures.append(f"{product_id}: base_price must be positive")
        except (TypeError, ValueError):
            failures.append(f"{product_id}: base_price is not numeric")

        if not _valid_skus(product.get("skus")):
            failures.append(f"{product_id}: skus must contain sku_id and numeric price")

        rag = product.get("rag_knowledge")
        if not isinstance(rag, dict) or not rag.get("marketing_description"):
            failures.append(f"{product_id}: rag_knowledge.marketing_description is required")
    return failures


def validate_db(products: list[dict[str, Any]], db_path: Path) -> list[str]:
    failures: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        db_ids = {
            row[0]
            for row in conn.execute(
                "SELECT product_id FROM products WHERE product_id IN (%s)"
                % ",".join("?" for _ in products),
                [product["product_id"] for product in products],
            ).fetchall()
        } if products else set()
    finally:
        conn.close()

    for product in products:
        product_id = product["product_id"]
        if product_id not in db_ids:
            failures.append(f"{product_id}: clean product has not been imported into SQLite")
        elif not (PRODUCT_IMAGE_DIR / f"{product_id}.jpg").exists() and str(product.get("image_url", "")).startswith("http"):
            failures.append(f"{product_id}: image is still remote and not cached for image search")
    return failures


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


if __name__ == "__main__":
    main()

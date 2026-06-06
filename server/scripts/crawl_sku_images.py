from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

SERVER_DIR = Path(__file__).resolve().parents[1]
STATIC_IMAGE_DIR = SERVER_DIR / "static" / "product_images"
OUTPUT_DIR = SERVER_DIR / "data_pipeline" / "output" / "sku_images"
DB_PATH = SERVER_DIR / "storage" / "shopguide.sqlite3"

APPLE_USER_AGENT = "Mozilla/5.0 (compatible; CartCompassChallengeBot/0.1; +local-development)"
IPHONE_17_PRO_BUY_URL = "https://www.apple.com/shop/buy-iphone/iphone-17-pro/6.3-inch-display-256gb-cosmic-orange-unlocked"
IPHONE_17_PRO_MAX_BUY_URL = "https://www.apple.com/shop/buy-iphone/iphone-17-pro/6.9-inch-display-256gb-cosmic-orange-unlocked"

APPLE_COLOR_MAP = {
    "宇宙橙": ("cosmicorange", "宇宙橙 Cosmic Orange"),
    "Cosmic Orange": ("cosmicorange", "宇宙橙 Cosmic Orange"),
    "冰川蓝": ("deepblue", "冰川蓝"),
    "远峰蓝": ("deepblue", "冰川蓝"),
    "Deep Blue": ("deepblue", "冰川蓝"),
    "钛金色": ("silver", "银色"),
    "银色": ("silver", "银色"),
    "深空黑": ("silver", "银色"),
    "Silver": ("silver", "银色"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl real SKU images from public product pages and attach them to local SKUs.")
    parser.add_argument("--product-id", default="p_digital_003")
    parser.add_argument("--source-url", default=IPHONE_17_PRO_MAX_BUY_URL)
    parser.add_argument("--image-slug", default="iphone-17-pro-max", help="Apple CDN finish-select slug, e.g. iphone-17-pro or iphone-17-pro-max.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "apple_iphone17promax_sku_images.json")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    html = fetch_text(args.source_url)
    source_images = extract_apple_finish_select_images(html, args.image_slug)
    if not source_images:
        raise SystemExit(f"No Apple {args.image_slug} finish-select images were found.")

    updated = attach_images_to_product(args.db, args.product_id, args.source_url, source_images)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"attached {len(updated['skus'])} SKU image mappings -> {args.output}")


def fetch_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": APPLE_USER_AGENT}, timeout=25)
    response.raise_for_status()
    return response.text


def fetch_bytes(url: str) -> bytes:
    response = requests.get(url, headers={"User-Agent": APPLE_USER_AGENT}, timeout=25)
    response.raise_for_status()
    return response.content


def extract_apple_finish_select_images(html: str, image_slug: str) -> dict[str, str]:
    escaped_slug = re.escape(image_slug)
    pattern = rf"https://store\.storeimages\.cdn-apple\.com/[^\"'<> ]+{escaped_slug}-finish-select-(deepblue|cosmicorange|silver)-202509[^\"'<> ]+"
    images: dict[str, str] = {}
    for match in re.finditer(pattern, html):
        color_key = match.group(1)
        url = match.group(0).replace("&amp;", "&")
        if "fmt=png-alpha" not in url:
            continue
        images.setdefault(color_key, url)
    return images


def attach_images_to_product(db_path: Path, product_id: str, source_page: str, source_images: dict[str, str]) -> dict[str, Any]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT skus_json FROM products WHERE product_id=?", (product_id,)).fetchone()
    if not row:
        raise SystemExit(f"Product not found: {product_id}")

    skus = json.loads(row["skus_json"])
    mappings: list[dict[str, Any]] = []
    for sku in skus:
        color_text = str((sku.get("properties") or {}).get("颜色", ""))
        color_key, canonical_color = resolve_color(color_text)
        if not color_key or color_key not in source_images:
            sku.pop("image_url", None)
            sku.pop("image_source_url", None)
            continue

        sku_id = sku["sku_id"]
        local_path = STATIC_IMAGE_DIR / f"{sku_id}.png"
        local_path.write_bytes(fetch_bytes(source_images[color_key]))
        sku["properties"]["颜色"] = canonical_color
        sku["image_url"] = f"/static/product_images/{local_path.name}"
        sku["image_source_url"] = source_images[color_key]
        mappings.append(
            {
                "sku_id": sku_id,
                "color": canonical_color,
                "local_image": sku["image_url"],
                "source_url": source_images[color_key],
            }
        )

    conn.execute("UPDATE products SET skus_json=? WHERE product_id=?", (json.dumps(skus, ensure_ascii=False), product_id))
    conn.commit()
    conn.close()
    return {
        "product_id": product_id,
        "source_page": source_page,
        "crawl_time": datetime.now(timezone.utc).isoformat(),
        "policy": "Only SKU images downloaded from the public source page are attached. Missing variants are left without fabricated images.",
        "skus": mappings,
    }


def resolve_color(color_text: str) -> tuple[str | None, str | None]:
    for token, mapping in APPLE_COLOR_MAP.items():
        if token.lower() in color_text.lower():
            return mapping
    return None, None


if __name__ == "__main__":
    main()

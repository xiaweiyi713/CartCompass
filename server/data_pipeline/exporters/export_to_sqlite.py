from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import requests
from PIL import Image

SERVER_DIR = Path(__file__).resolve().parents[2]
if str(SERVER_DIR) not in sys.path:
    sys.path.append(str(SERVER_DIR))

from app.config import DB_PATH, PRODUCT_IMAGE_DIR
from app.db.database import connect, init_schema
from app.rag.text_vectorizer import HashingVectorizer


def export_products_to_sqlite(
    products: list[dict[str, Any]],
    db_path: Path = DB_PATH,
    replace_existing: bool = True,
    cache_images: bool = True,
) -> int:
    conn = connect(db_path)
    init_schema(conn)
    vectorizer = HashingVectorizer()
    count = 0
    for data in products:
        search_text = build_search_text(data)
        image_url = resolve_image_url(data) if cache_images else data.get("image_url", "")
        sql = "INSERT OR REPLACE" if replace_existing else "INSERT OR IGNORE"
        conn.execute(
            f"""
            {sql} INTO products
            (product_id, title, brand, category, sub_category, base_price, image_url, skus_json, rag_json, search_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["product_id"],
                data["title"],
                data["brand"],
                data["category"],
                data["sub_category"],
                float(data["base_price"]),
                image_url,
                json.dumps(data.get("skus", []), ensure_ascii=False),
                json.dumps(data.get("rag_knowledge", {}), ensure_ascii=False),
                search_text,
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO product_vectors (product_id, vector_json) VALUES (?, ?)",
            (data["product_id"], json.dumps(vectorizer.embed(search_text))),
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def resolve_image_url(data: dict[str, Any]) -> str:
    """Cache crawler images locally when possible so remote products can join image search."""
    image_url = str(data.get("image_url") or "")
    if not image_url or image_url.startswith("/static/"):
        return image_url

    product_id = str(data["product_id"])
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return _download_image(image_url, product_id) or image_url

    local_path = Path(image_url).expanduser()
    if local_path.exists():
        return _save_image(local_path.read_bytes(), product_id) or image_url
    return image_url


def _download_image(url: str, product_id: str) -> str:
    try:
        response = requests.get(url, timeout=12, headers={"User-Agent": "ShopGuideBot/1.0"})
        response.raise_for_status()
    except requests.RequestException:
        return ""
    return _save_image(response.content, product_id)


def _save_image(content: bytes, product_id: str) -> str:
    try:
        with Image.open(io.BytesIO(content)) as image:
            rgb = _flatten_to_rgb(image)
            PRODUCT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            destination = PRODUCT_IMAGE_DIR / f"{product_id}.jpg"
            rgb.save(destination, "JPEG", quality=88, optimize=True)
    except OSError:
        return ""
    return f"/static/product_images/{product_id}.jpg"


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return image.convert("RGB")


def load_clean_products(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("clean product file must be a JSON list")
    return data


def build_search_text(data: dict[str, Any]) -> str:
    rag = data.get("rag_knowledge", {})
    faq = " ".join(f"{item.get('question', '')} {item.get('answer', '')}" for item in rag.get("official_faq", []))
    reviews = " ".join(item.get("content", "") for item in rag.get("user_reviews", []))
    attributes = json.dumps(data.get("attributes", {}), ensure_ascii=False)
    return " ".join(
        [
            data.get("title", ""),
            data.get("brand", ""),
            data.get("category", ""),
            data.get("sub_category", ""),
            rag.get("marketing_description", ""),
            faq,
            reviews,
            attributes,
        ]
    )

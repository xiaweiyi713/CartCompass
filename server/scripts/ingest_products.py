from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import DB_PATH, PRODUCT_IMAGE_DIR, REPO_DIR
from app.db.database import connect, init_schema
from app.rag.text_vectorizer import HashingVectorizer


def build_search_text(data: dict) -> str:
    rag = data.get("rag_knowledge", {})
    faq = " ".join(f"{item.get('question', '')} {item.get('answer', '')}" for item in rag.get("official_faq", []))
    reviews = " ".join(item.get("content", "") for item in rag.get("user_reviews", []))
    return " ".join(
        [
            data.get("title", ""),
            data.get("brand", ""),
            data.get("category", ""),
            data.get("sub_category", ""),
            rag.get("marketing_description", ""),
            faq,
            reviews,
        ]
    )


def find_image(root: Path, product_id: str) -> Path | None:
    matches = list(root.rglob(f"{product_id}_live.jpg"))
    return matches[0] if matches else None


def main() -> None:
    raw_root = REPO_DIR / "data" / "extracted"
    if not raw_root.exists():
        raise SystemExit("请先解压 data/ecommerce_agent_dataset_供参考.zip 到 data/extracted")

    PRODUCT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect(DB_PATH)
    init_schema(conn)
    conn.execute("DELETE FROM product_vectors")
    conn.execute("DELETE FROM products")

    vectorizer = HashingVectorizer()
    json_files = sorted(raw_root.rglob("*.json"))
    for path in json_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        product_id = data["product_id"]
        image_src = find_image(raw_root, product_id)
        if image_src:
            image_dst = PRODUCT_IMAGE_DIR / f"{product_id}.jpg"
            shutil.copyfile(image_src, image_dst)
            image_url = f"/static/product_images/{product_id}.jpg"
        else:
            image_url = ""
        search_text = build_search_text(data)
        conn.execute(
            """
            INSERT INTO products
            (product_id, title, brand, category, sub_category, base_price, image_url, skus_json, rag_json, search_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
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
            "INSERT INTO product_vectors (product_id, vector_json) VALUES (?, ?)",
            (product_id, json.dumps(vectorizer.embed(search_text))),
        )
    conn.commit()
    print(f"ingested {len(json_files)} products into {DB_PATH}")


if __name__ == "__main__":
    main()

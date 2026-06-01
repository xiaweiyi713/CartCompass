from __future__ import annotations

import io
import sqlite3

import pytest
from PIL import Image

from data_pipeline.cleaners.normalize_product import normalize_products
from data_pipeline.cleaners.price_parser import parse_price
from data_pipeline.exporters import export_to_sqlite
from app.db.database import connect, init_schema
from app.rag.semantic_text import TextEmbeddingStore


def test_parse_price_uses_lowest_price_in_range() -> None:
    assert parse_price("¥89-109") == 89.0
    assert parse_price("RMB 1,299.00") == 1299.0
    assert parse_price("暂无价格") == 0.0


def test_normalize_product_builds_shopguide_schema() -> None:
    raw = [
        {
            "source": "public_demo",
            "source_category": "美妆护肤",
            "source_sub_category": "洁面",
            "name": "PureLab 清爽控油氨基酸洗面奶",
            "brand": "PureLab",
            "price_text": "¥89",
            "description": "适合油皮和混油皮，清爽控油，温和不含酒精。",
            "image_url": "https://example.com/product.jpg",
            "product_url": "https://example.com/product/1",
        }
    ]

    products = normalize_products(raw, "p_test")

    assert len(products) == 1
    product = products[0]
    assert product["title"] == "PureLab 清爽控油氨基酸洗面奶"
    assert product["base_price"] == 89.0
    assert product["price_currency"] == "CNY"
    assert product["category"] == "美妆护肤"
    assert product["sub_category"] == "洁面"
    assert product["attributes"]["skin_type"] == ["油皮"]
    assert "不含酒精" in product["rag_knowledge"]["marketing_description"]


def test_normalize_product_converts_usd_to_cny() -> None:
    raw = [
        {
            "source": "anker_official_store",
            "source_category": "数码电子",
            "source_sub_category": "充电设备",
            "name": "Anker Nano Charger",
            "brand": "Anker",
            "price_text": "25.99",
            "price_currency": "USD",
            "description": "Fast charging compact charger.",
            "image_url": "https://example.com/charger.png",
            "product_url": "https://example.com/products/charger",
        }
    ]

    product = normalize_products(raw, "p_test", {"USD": 6.8})[0]

    assert product["base_price"] == 176.73
    assert product["price_currency"] == "CNY"
    assert product["source_price"] == 25.99
    assert product["source_price_currency"] == "USD"
    assert product["exchange_rate_to_cny"] == 6.8


def test_export_caches_remote_image_for_crawled_product(tmp_path, monkeypatch) -> None:
    image_bytes = io.BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 128)).save(image_bytes, format="PNG")

    class FakeResponse:
        content = image_bytes.getvalue()

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(export_to_sqlite, "PRODUCT_IMAGE_DIR", tmp_path / "images")
    monkeypatch.setattr(export_to_sqlite.requests, "get", lambda *args, **kwargs: FakeResponse())

    product = normalize_products(
        [
            {
                "source": "anker_official_store",
                "source_category": "数码电子",
                "source_sub_category": "充电设备",
                "name": "Anker Nano Charger",
                "brand": "Anker",
                "price_text": "25.99",
                "price_currency": "USD",
                "description": "Fast charging compact charger.",
                "image_url": "https://example.com/charger.png",
                "product_url": "https://example.com/products/charger",
            }
        ],
        "p_test",
        {"USD": 6.8},
    )[0]

    count = export_to_sqlite.export_products_to_sqlite([product], db_path=tmp_path / "shop.sqlite3")

    assert count == 1
    assert (tmp_path / "images" / f"{product['product_id']}.jpg").exists()
    conn = sqlite3.connect(tmp_path / "shop.sqlite3")
    try:
        image_url = conn.execute("SELECT image_url FROM products WHERE product_id=?", (product["product_id"],)).fetchone()[0]
    finally:
        conn.close()
    assert image_url == f"/static/product_images/{product['product_id']}.jpg"


def test_text_embedding_store_caches_product_vectors(tmp_path) -> None:
    class FakeEmbeddingClient:
        config = type("Config", (), {"provider": "fake", "model": "semantic-v1"})()
        calls = 0

        @property
        def is_configured(self) -> bool:
            return True

        @property
        def identity(self) -> tuple[str, str]:
            return self.config.provider, self.config.model

        def embed(self, text: str) -> list[float]:
            self.calls += 1
            return [float(len(text)), 1.0]

    conn = connect(tmp_path / "shop.sqlite3")
    init_schema(conn)
    conn.execute(
        """
        INSERT INTO products
        (product_id, title, brand, category, sub_category, base_price, image_url, skus_json, rag_json, search_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("p_semantic", "轻薄长续航手机", "Demo", "数码电子", "智能手机", 3999, "", "[]", "{}", "轻薄 长续航 大电池 手机"),
    )
    conn.commit()

    client = FakeEmbeddingClient()
    store = TextEmbeddingStore(conn, client, allow_request_upsert=True)  # type: ignore[arg-type]
    first = store.vector_for_product("p_semantic", "轻薄 长续航 大电池 手机")
    second = store.vector_for_product("p_semantic", "轻薄 长续航 大电池 手机")

    assert first == pytest.approx(second)
    assert client.calls == 1
    assert conn.execute("SELECT COUNT(*) FROM text_embedding_vectors").fetchone()[0] == 1


def test_text_embedding_store_skips_request_time_product_upsert(tmp_path) -> None:
    class FakeEmbeddingClient:
        config = type("Config", (), {"provider": "fake", "model": "semantic-v1"})()
        calls = 0

        @property
        def is_configured(self) -> bool:
            return True

        @property
        def identity(self) -> tuple[str, str]:
            return self.config.provider, self.config.model

        def embed(self, text: str) -> list[float]:
            self.calls += 1
            return [float(len(text)), 1.0]

    conn = connect(tmp_path / "shop.sqlite3")
    init_schema(conn)

    client = FakeEmbeddingClient()
    store = TextEmbeddingStore(conn, client)  # type: ignore[arg-type]
    vector = store.vector_for_product("p_missing", "轻薄 长续航 大电池 手机")

    assert vector is None
    assert client.calls == 0
    assert conn.execute("SELECT COUNT(*) FROM text_embedding_vectors").fetchone()[0] == 0


def test_text_embedding_store_precomputes_missing_vectors(tmp_path) -> None:
    class FakeEmbeddingClient:
        config = type("Config", (), {"provider": "fake", "model": "semantic-v1"})()
        calls = 0

        @property
        def is_configured(self) -> bool:
            return True

        @property
        def identity(self) -> tuple[str, str]:
            return self.config.provider, self.config.model

        def embed(self, text: str) -> list[float]:
            self.calls += 1
            return [float(len(text)), 1.0]

    conn = connect(tmp_path / "shop.sqlite3")
    init_schema(conn)
    for product_id, search_text in [
        ("p_semantic_1", "轻薄 长续航 大电池 手机"),
        ("p_semantic_2", "油皮 防晒 不含酒精"),
    ]:
        conn.execute(
            """
            INSERT INTO products
            (product_id, title, brand, category, sub_category, base_price, image_url, skus_json, rag_json, search_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, product_id, "Demo", "数码电子", "智能手机", 3999, "", "[]", "{}", search_text),
        )
    conn.commit()

    client = FakeEmbeddingClient()
    store = TextEmbeddingStore(conn, client)  # type: ignore[arg-type]
    written = store.precompute_missing(limit=1)

    assert written == 1
    assert client.calls == 1
    assert conn.execute("SELECT COUNT(*) FROM text_embedding_vectors").fetchone()[0] == 1

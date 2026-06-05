from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Iterator

from app.config import DB_PATH

# Committed snapshot used to bootstrap a fresh checkout / container so the demo
# catalog is available with zero manual ingest steps.
SEED_DB_PATH = DB_PATH.parent / "seed.sqlite3"


def _seed_if_missing(db_path: Path) -> None:
    """Copy the committed seed database into place when the runtime DB is absent.

    This only applies to the default production DB path. Unit tests that pass
    their own temp path (or an explicit DB) are never seeded, so fixtures stay
    isolated and deterministic.
    """
    if db_path != DB_PATH or db_path.exists() or not SEED_DB_PATH.exists():
        return
    shutil.copyfile(SEED_DB_PATH, db_path)


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _seed_if_missing(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def iter_rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Iterator[sqlite3.Row]:
    yield from conn.execute(sql, params)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            brand TEXT NOT NULL,
            category TEXT NOT NULL,
            sub_category TEXT NOT NULL,
            base_price REAL NOT NULL,
            image_url TEXT NOT NULL,
            stock_status TEXT NOT NULL DEFAULT 'in_stock',
            inventory_count INTEGER NOT NULL DEFAULT 8,
            skus_json TEXT NOT NULL,
            rag_json TEXT NOT NULL,
            search_text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS product_chunks (
            chunk_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
            chunk_type TEXT NOT NULL,
            ordinal INTEGER NOT NULL DEFAULT 0,
            chunk_text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS product_vectors (
            product_id TEXT PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
            vector_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS text_embedding_vectors (
            product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            source_text_hash TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (product_id, provider, model)
        );

        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
        CREATE INDEX IF NOT EXISTS idx_products_sub_category ON products(sub_category);
        CREATE INDEX IF NOT EXISTS idx_products_price ON products(base_price);
        CREATE INDEX IF NOT EXISTS idx_product_chunks_product ON product_chunks(product_id);
        CREATE INDEX IF NOT EXISTS idx_product_chunks_type ON product_chunks(chunk_type);
        CREATE INDEX IF NOT EXISTS idx_text_embedding_vectors_model ON text_embedding_vectors(provider, model);
        """
    )
    _ensure_column(conn, "products", "stock_status", "TEXT NOT NULL DEFAULT 'in_stock'")
    _ensure_column(conn, "products", "inventory_count", "INTEGER NOT NULL DEFAULT 8")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_products_stock ON products(stock_status, inventory_count)")
    _ensure_product_chunks(conn)
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_product_chunks(conn: sqlite3.Connection) -> None:
    product_count = conn.execute("SELECT COUNT(*) AS count FROM products").fetchone()["count"]
    chunk_count = conn.execute("SELECT COUNT(*) AS count FROM product_chunks").fetchone()["count"]
    if not product_count or chunk_count:
        return
    rows = conn.execute("SELECT product_id, title, brand, category, sub_category, rag_json FROM products").fetchall()
    for row in rows:
        for ordinal, (chunk_type, chunk_text) in enumerate(_chunks_for_product(row)):
            conn.execute(
                """
                INSERT OR REPLACE INTO product_chunks (chunk_id, product_id, chunk_type, ordinal, chunk_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (f"{row['product_id']}::{chunk_type}::{ordinal}", row["product_id"], chunk_type, ordinal, chunk_text),
            )


def _chunks_for_product(row: sqlite3.Row) -> list[tuple[str, str]]:
    import json

    rag = json.loads(row["rag_json"] or "{}")
    chunks: list[tuple[str, str]] = [
        (
            "identity",
            " ".join(
                str(part)
                for part in [row["title"], row["brand"], row["category"], row["sub_category"]]
                if part
            ),
        )
    ]
    marketing = str(rag.get("marketing_description") or "").strip()
    if marketing:
        chunks.append(("detail", marketing[:900]))
    for index, faq in enumerate(rag.get("official_faq") if isinstance(rag.get("official_faq"), list) else []):
        if not isinstance(faq, dict):
            continue
        text = f"{faq.get('question', '')} {faq.get('answer', '')}".strip()
        if text:
            chunks.append((f"faq", text[:700]))
    for review in rag.get("user_reviews") if isinstance(rag.get("user_reviews"), list) else []:
        if not isinstance(review, dict):
            continue
        text = str(review.get("content") or "").strip()
        rating = review.get("rating")
        if text:
            chunks.append(("review", f"评分 {rating}：{text}"[:600]))
    return [(chunk_type, text) for chunk_type, text in chunks if text]

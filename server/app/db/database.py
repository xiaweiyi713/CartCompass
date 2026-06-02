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
            skus_json TEXT NOT NULL,
            rag_json TEXT NOT NULL,
            search_text TEXT NOT NULL
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
        CREATE INDEX IF NOT EXISTS idx_text_embedding_vectors_model ON text_embedding_vectors(provider, model);
        """
    )
    conn.commit()

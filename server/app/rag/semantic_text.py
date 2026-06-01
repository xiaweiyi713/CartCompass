from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass

import httpx

from app.config import (
    TEXT_EMBEDDING_ALLOW_REQUEST_UPSERT,
    TEXT_EMBEDDING_API_KEY,
    TEXT_EMBEDDING_BASE_URL,
    TEXT_EMBEDDING_MODEL,
    TEXT_EMBEDDING_TIMEOUT_SECONDS,
)


@dataclass(frozen=True)
class TextEmbeddingConfig:
    provider: str = "openai_compatible"
    model: str = TEXT_EMBEDDING_MODEL
    api_key: str = TEXT_EMBEDDING_API_KEY
    base_url: str = TEXT_EMBEDDING_BASE_URL
    timeout_seconds: float = TEXT_EMBEDDING_TIMEOUT_SECONDS

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.model and self.base_url)


class TextEmbeddingClient:
    def __init__(self, config: TextEmbeddingConfig | None = None) -> None:
        self.config = config or TextEmbeddingConfig()

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    @property
    def identity(self) -> tuple[str, str]:
        return self.config.provider, self.config.model

    def embed(self, text: str) -> list[float] | None:
        if not self.config.is_configured:
            return None
        endpoint = self._embedding_endpoint()
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self._sanitize_api_key(self.config.api_key)}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self.config.model, "input": text},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            return None
        vector = data[0].get("embedding") if isinstance(data[0], dict) else None
        if not isinstance(vector, list):
            return None
        values = [float(item) for item in vector if isinstance(item, int | float)]
        return normalize_vector(values) if values else None

    def _embedding_endpoint(self) -> str:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/embeddings"):
            return base_url
        return f"{base_url}/embeddings"

    def _sanitize_api_key(self, api_key: str) -> str:
        compact = re.sub(r"[\s\u200b\u200c\u200d\ufeff\u2060]+", "", api_key or "")
        match = re.search(r"sk-[A-Za-z0-9_-]+", compact)
        return match.group(0) if match else compact.strip()


class TextEmbeddingStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        client: TextEmbeddingClient | None = None,
        allow_request_upsert: bool = TEXT_EMBEDDING_ALLOW_REQUEST_UPSERT,
    ) -> None:
        self.conn = conn
        self.client = client or TextEmbeddingClient()
        self.allow_request_upsert = allow_request_upsert
        self._query_cache: dict[str, list[float]] = {}
        self._ensure_schema()

    @property
    def is_configured(self) -> bool:
        return self.client.is_configured

    @property
    def identity(self) -> tuple[str, str]:
        return self.client.identity

    def embed_query(self, text: str) -> list[float] | None:
        if not self.client.is_configured:
            return None
        key = self._cache_key(text)
        if key not in self._query_cache:
            vector = self.client.embed(text)
            if vector:
                self._query_cache[key] = vector
        return self._query_cache.get(key)

    def vector_for_product(self, product_id: str, source_text: str) -> list[float] | None:
        if not self.client.is_configured:
            return None
        provider, model = self.client.identity
        text_hash = self._text_hash(source_text)
        row = self.conn.execute(
            """
            SELECT vector_json, source_text_hash
            FROM text_embedding_vectors
            WHERE product_id=? AND provider=? AND model=?
            """,
            (product_id, provider, model),
        ).fetchone()
        if row and row["source_text_hash"] == text_hash:
            try:
                return normalize_vector([float(item) for item in json.loads(row["vector_json"])])
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        if not self.allow_request_upsert:
            return None
        vector = self.client.embed(source_text)
        if not vector:
            return None
        normalized = normalize_vector(vector)
        self.upsert_product_vector(product_id, source_text, normalized)
        return normalized

    def upsert_product_vector(self, product_id: str, source_text: str, vector: list[float]) -> None:
        provider, model = self.client.identity
        self.conn.execute(
            """
            INSERT OR REPLACE INTO text_embedding_vectors
            (product_id, provider, model, source_text_hash, vector_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                product_id,
                provider,
                model,
                self._text_hash(source_text),
                json.dumps(normalize_vector(vector)),
            ),
        )
        self.conn.commit()

    def precompute_missing(self, limit: int | None = None) -> int:
        if not self.client.is_configured:
            return 0
        provider, model = self.client.identity
        rows = self.conn.execute(
            """
            SELECT product_id, search_text
            FROM products
            ORDER BY product_id
            """
        ).fetchall()
        written = 0
        for row in rows:
            if limit is not None and written >= limit:
                break
            text_hash = self._text_hash(row["search_text"])
            existing = self.conn.execute(
                """
                SELECT 1 FROM text_embedding_vectors
                WHERE product_id=? AND provider=? AND model=? AND source_text_hash=?
                """,
                (row["product_id"], provider, model, text_hash),
            ).fetchone()
            if existing:
                continue
            vector = self.client.embed(row["search_text"])
            if not vector:
                continue
            self.upsert_product_vector(row["product_id"], row["search_text"], vector)
            written += 1
        return written

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS text_embedding_vectors (
                product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                source_text_hash TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (product_id, provider, model)
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_text_embedding_vectors_model ON text_embedding_vectors(provider, model)"
        )
        self.conn.commit()

    def _text_hash(self, text: str) -> str:
        return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()

    def _cache_key(self, text: str) -> str:
        provider, model = self.client.identity
        return f"{provider}:{model}:{self._text_hash(text)}"


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]

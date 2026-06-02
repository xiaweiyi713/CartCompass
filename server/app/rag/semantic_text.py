from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import sqlite3
from dataclasses import dataclass

import httpx
from PIL import Image

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
        self.disabled_reason: str | None = None

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    @property
    def identity(self) -> tuple[str, str]:
        return self.config.provider, self.config.model

    @property
    def is_multimodal(self) -> bool:
        # Doubao vision embeddings (e.g. doubao-embedding-vision-*) use the
        # /embeddings/multimodal endpoint with a structured `input` list and a
        # `data: {embedding: [...]}` response, unlike OpenAI-style text embeddings.
        return "vision" in (self.config.model or "").lower()

    def embed(self, text: str) -> list[float] | None:
        if not self.config.is_configured or self.disabled_reason:
            return None
        if self.is_multimodal:
            body = {"model": self.config.model, "input": [{"type": "text", "text": text}]}
        else:
            body = {"model": self.config.model, "input": text}
        payload = self._post(body, disable_on_client_error=True)
        return self._vector_from_payload(payload) if payload else None

    def embed_image(self, image_bytes: bytes) -> list[float] | None:
        """Embed an image into the shared image-text space (multimodal models
        only). Enables cross-modal "photo → product" search. A bad image does not
        disable the client (unlike a config-level auth/endpoint error)."""
        if not self.config.is_configured or self.disabled_reason or not self.is_multimodal:
            return None
        data_uri = self._image_data_uri(image_bytes)
        if not data_uri:
            return None
        body = {"model": self.config.model, "input": [{"type": "image_url", "image_url": {"url": data_uri}}]}
        payload = self._post(body, disable_on_client_error=False)
        return self._vector_from_payload(payload) if payload else None

    def _post(self, body: dict, disable_on_client_error: bool) -> dict | None:
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.post(
                    self._embedding_endpoint(),
                    headers={
                        "Authorization": f"Bearer {self._sanitize_api_key(self.config.api_key)}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            if disable_on_client_error and exc.response.status_code in {400, 401, 403, 404}:
                self.disabled_reason = f"embedding endpoint returned HTTP {exc.response.status_code}"
            return None
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return None

    def _image_data_uri(self, image_bytes: bytes) -> str | None:
        try:
            with Image.open(io.BytesIO(image_bytes)) as raw:
                rgb = raw.convert("RGB")
                longest = max(rgb.size)
                if longest > 768:
                    ratio = 768 / longest
                    rgb = rgb.resize((max(1, int(rgb.width * ratio)), max(1, int(rgb.height * ratio))))
                buffer = io.BytesIO()
                rgb.save(buffer, format="JPEG", quality=85)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
        except (OSError, ValueError):
            return None

    def _vector_from_payload(self, payload: object) -> list[float] | None:
        data = payload.get("data") if isinstance(payload, dict) else None
        vector = None
        if isinstance(data, dict):  # multimodal: {"data": {"embedding": [...]}}
            vector = data.get("embedding")
        elif isinstance(data, list) and data and isinstance(data[0], dict):  # text: {"data": [{"embedding": [...]}]}
            vector = data[0].get("embedding")
        if not isinstance(vector, list):
            return None
        values = [float(item) for item in vector if isinstance(item, int | float)]
        return normalize_vector(values) if values else None

    def _embedding_endpoint(self) -> str:
        base_url = self.config.base_url.rstrip("/")
        suffix = "/embeddings/multimodal" if self.is_multimodal else "/embeddings"
        if base_url.endswith(suffix):
            return base_url
        if base_url.endswith("/embeddings"):
            base_url = base_url[: -len("/embeddings")]
        return f"{base_url}{suffix}"

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

    def cached_vector(self, product_id: str) -> list[float] | None:
        """Read a product's precomputed text vector for the current model, by id
        only (ignores text-hash freshness). Used by cross-modal image search to
        compare an image vector against product text vectors in the shared space."""
        provider, model = self.client.identity
        row = self.conn.execute(
            "SELECT vector_json FROM text_embedding_vectors WHERE product_id=? AND provider=? AND model=?",
            (product_id, provider, model),
        ).fetchone()
        if not row:
            return None
        try:
            return normalize_vector([float(item) for item in json.loads(row["vector_json"])])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

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

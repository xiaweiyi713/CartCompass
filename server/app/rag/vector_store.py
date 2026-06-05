from __future__ import annotations

import json
import logging
import re
import sqlite3
from hashlib import sha1
from dataclasses import dataclass
from typing import Protocol

from app.config import CHROMA_COLLECTION, CHROMA_PATH, VECTOR_STORE_BACKEND
from app.observability import observability
from app.rag.semantic_text import TextEmbeddingConfig
from app.rag.semantic_text import cosine_similarity


class VectorStore(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def vector_kind(self) -> str:
        ...

    def status(self) -> dict[str, str | bool | None]:
        ...

    def score(self, query_vector: list[float], candidate_rows: list[sqlite3.Row], top_k: int) -> dict[str, float]:
        ...


@dataclass
class SQLiteHashVectorStore:
    @property
    def name(self) -> str:
        return "sqlite_hashing_vector"

    @property
    def vector_kind(self) -> str:
        return "hashing"

    def status(self) -> dict[str, str | bool | None]:
        return {
            "configured_backend": VECTOR_STORE_BACKEND,
            "active_backend": self.name,
            "vector_kind": self.vector_kind,
            "chroma_enabled": False,
            "chroma_path": None,
            "provider": None,
            "model": None,
            "fallback_reason": "VECTOR_STORE_BACKEND is not chroma",
        }

    def score(self, query_vector: list[float], candidate_rows: list[sqlite3.Row], top_k: int) -> dict[str, float]:
        return {
            row["product_id"]: cosine_similarity(query_vector, json.loads(row["vector_json"]))
            for row in candidate_rows
        }


class ChromaVectorStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        try:
            import chromadb  # type: ignore
            from chromadb.config import Settings  # type: ignore
        except Exception as exc:  # noqa: BLE001 - optional dependency.
            raise RuntimeError("chromadb is not installed") from exc

        logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
        logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
        self._vector_kind = "hashing"
        self.provider: str | None = None
        self.model: str | None = None
        if not self._try_sync_text_embeddings(conn):
            self.collection = self.client.get_or_create_collection(
                f"{CHROMA_COLLECTION}_hash",
                metadata={"hnsw:space": "cosine", "vector_kind": "hashing"},
            )
            self._sync_hashing_vectors(conn)

    @property
    def name(self) -> str:
        return "chroma_text_embedding" if self._vector_kind == "text_embedding" else "chroma_hashing_vector"

    @property
    def vector_kind(self) -> str:
        return self._vector_kind

    def status(self) -> dict[str, str | bool | None]:
        return {
            "configured_backend": VECTOR_STORE_BACKEND,
            "active_backend": self.name,
            "vector_kind": self.vector_kind,
            "chroma_enabled": True,
            "chroma_path": str(CHROMA_PATH),
            "collection": self.collection.name,
            "provider": self.provider,
            "model": self.model,
            "fallback_reason": None if self._vector_kind == "text_embedding" else "using local hashing vectors",
        }

    def score(self, query_vector: list[float], candidate_rows: list[sqlite3.Row], top_k: int) -> dict[str, float]:
        if not candidate_rows:
            return {}
        candidate_ids = {row["product_id"] for row in candidate_rows}
        result = self.collection.query(
            query_embeddings=[query_vector],
            n_results=max(top_k, min(len(candidate_ids), 80)),
        )
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        scores: dict[str, float] = {}
        for product_id, distance in zip(ids, distances):
            if product_id in candidate_ids:
                scores[str(product_id)] = max(0.0, 1.0 - float(distance))
        return scores

    def _try_sync_text_embeddings(self, conn: sqlite3.Connection) -> bool:
        config = TextEmbeddingConfig()
        if not config.is_configured:
            return False
        rows = conn.execute(
            """
            SELECT p.product_id, p.title, p.category, p.sub_category, e.vector_json
            FROM products p
            JOIN text_embedding_vectors e ON p.product_id = e.product_id
            WHERE e.provider=? AND e.model=?
            ORDER BY p.product_id
            """,
            (config.provider, config.model),
        ).fetchall()
        if not rows:
            return False
        self._vector_kind = "text_embedding"
        self.provider = config.provider
        self.model = config.model
        collection_name = self._collection_name(config.provider, config.model)
        self.collection = self.client.get_or_create_collection(
            collection_name,
            metadata={
                "hnsw:space": "cosine",
                "vector_kind": "text_embedding",
                "provider": config.provider,
                "model": config.model,
            },
        )
        self._upsert_rows(rows)
        return True

    def _sync_hashing_vectors(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT p.product_id, p.title, p.category, p.sub_category, v.vector_json
            FROM products p
            JOIN product_vectors v ON p.product_id = v.product_id
            ORDER BY p.product_id
            """
        ).fetchall()
        if not rows:
            return
        self._upsert_rows(rows)

    def _upsert_rows(self, rows: list[sqlite3.Row]) -> None:
        self.collection.upsert(
            ids=[row["product_id"] for row in rows],
            embeddings=[json.loads(row["vector_json"]) for row in rows],
            metadatas=[
                {
                    "title": row["title"],
                    "category": row["category"],
                    "sub_category": row["sub_category"],
                }
                for row in rows
            ],
        )

    def _collection_name(self, provider: str, model: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", model).strip("_")[:32] or "model"
        digest = sha1(f"{provider}:{model}".encode("utf-8")).hexdigest()[:8]
        return f"{CHROMA_COLLECTION}_text_{slug}_{digest}"


def build_vector_store(conn: sqlite3.Connection) -> VectorStore:
    if VECTOR_STORE_BACKEND == "chroma":
        try:
            store = ChromaVectorStore(conn)
            observability.add_current_step(
                "vector_store",
                {
                    "backend": store.name,
                    "vector_kind": store.vector_kind,
                    "provider": getattr(store, "provider", None),
                    "model": getattr(store, "model", None),
                    "path": str(CHROMA_PATH),
                },
            )
            return store
        except Exception as exc:  # noqa: BLE001 - optional dependency/fallback.
            observability.add_current_step("vector_store", {"backend": "sqlite_fallback", "chroma_error": str(exc)})
    return SQLiteHashVectorStore()

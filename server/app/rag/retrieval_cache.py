from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any

from app.models.schemas import Product


@dataclass(frozen=True)
class CachedRetrievalResult:
    products: list[Product]
    created_at: float
    retrieval_stack: str


class RetrievalCache:
    def __init__(self, max_entries: int = 192, ttl_seconds: float = 120.0) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._items: OrderedDict[str, CachedRetrievalResult] = OrderedDict()

    def key(
        self,
        *,
        query: str,
        constraints: Any,
        limit: int,
        retrieval_identity: dict[str, Any],
    ) -> str:
        payload = {
            "query": self._normalize_text(query),
            "constraints": self._stable_constraints(constraints),
            "limit": limit,
            "retrieval_identity": retrieval_identity,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(raw.encode("utf-8"), digest_size=16).hexdigest()

    def get(self, key: str) -> CachedRetrievalResult | None:
        item = self._items.get(key)
        if not item:
            return None
        if time.monotonic() - item.created_at > self.ttl_seconds:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return CachedRetrievalResult(
            products=[product.model_copy(deep=True) for product in item.products],
            created_at=item.created_at,
            retrieval_stack=item.retrieval_stack,
        )

    def set(self, key: str, products: list[Product], retrieval_stack: str) -> None:
        self._items[key] = CachedRetrievalResult(
            products=[product.model_copy(deep=True) for product in products],
            created_at=time.monotonic(),
            retrieval_stack=retrieval_stack,
        )
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def _stable_constraints(self, constraints: Any) -> dict[str, Any]:
        payload = asdict(constraints)
        for key, value in list(payload.items()):
            if isinstance(value, list):
                payload[key] = sorted(str(item).strip().lower() for item in value if str(item).strip())
        return payload

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.strip().lower().split())

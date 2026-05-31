from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any

from app.rag.product_repository import SearchConstraints


@dataclass(frozen=True)
class CachedRecommendationReply:
    text: str
    source: str
    created_at: float


class RecommendationCache:
    def __init__(self, max_entries: int = 128, ttl_seconds: float = 180.0) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._items: OrderedDict[str, CachedRecommendationReply] = OrderedDict()

    def key(
        self,
        *,
        message: str,
        constraints: SearchConstraints,
        products: list[Any],
        model_identity: dict[str, Any],
    ) -> str:
        payload = {
            "message": self._normalize_text(message),
            "constraints": self._stable_constraints(constraints),
            "products": [
                {
                    "id": getattr(product, "product_id", ""),
                    "price": getattr(product, "base_price", None),
                }
                for product in products[:5]
            ],
            "model": model_identity,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(raw.encode("utf-8"), digest_size=16).hexdigest()

    def get(self, key: str) -> CachedRecommendationReply | None:
        item = self._items.get(key)
        if not item:
            return None
        if time.monotonic() - item.created_at > self.ttl_seconds:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return item

    def set(self, key: str, text: str, source: str) -> None:
        if not text.strip():
            return
        self._items[key] = CachedRecommendationReply(text=text, source=source, created_at=time.monotonic())
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def _stable_constraints(self, constraints: SearchConstraints) -> dict[str, Any]:
        payload = asdict(constraints)
        for key, value in list(payload.items()):
            if isinstance(value, list):
                payload[key] = sorted(str(item).strip().lower() for item in value if str(item).strip())
        return payload

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.strip().lower().split())

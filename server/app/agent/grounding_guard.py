from __future__ import annotations

import re

from app.models.schemas import Product
from app.observability import observability
from app.rag.product_repository import SearchConstraints


RISKY_UNGROUNDED_TERMS = [
    "优惠券",
    "领券",
    "满减",
    "限时折扣",
    "官方补贴",
    "包邮",
    "现货",
    "库存充足",
    "销量第一",
    "全网最低",
]


class GroundingGuard:
    def validate(
        self,
        text: str | None,
        products: list[Product],
        constraints: SearchConstraints,
    ) -> str | None:
        if not text:
            observability.increment("grounding_guard_empty")
            return None
        normalized = text.strip()
        if not normalized:
            observability.increment("grounding_guard_empty")
            return None
        if not self.is_safe(normalized, products, constraints):
            return None
        if "来自商品库" not in normalized and "商品库" not in normalized:
            normalized = f"以下信息来自本地商品库。{normalized}"
        observability.increment("grounding_guard_passes")
        observability.add_current_step(
            "grounding_guard",
            {"status": "passed", "product_ids": [product.product_id for product in products[:5]]},
        )
        return normalized

    def is_safe(
        self,
        text: str | None,
        products: list[Product],
        constraints: SearchConstraints,
    ) -> bool:
        if not text:
            return True
        normalized = text.strip()
        if not normalized:
            return True
        if any(term in normalized for term in RISKY_UNGROUNDED_TERMS):
            observability.increment("grounding_guard_blocks")
            observability.add_current_step(
                "grounding_guard",
                {"status": "blocked", "reason": "risky_ungrounded_terms"},
            )
            return False
        if self._has_unsupported_price(normalized, products, constraints):
            observability.increment("grounding_guard_blocks")
            observability.add_current_step(
                "grounding_guard",
                {"status": "blocked", "reason": "unsupported_price"},
            )
            return False
        return True

    def _has_unsupported_price(
        self,
        text: str,
        products: list[Product],
        constraints: SearchConstraints,
    ) -> bool:
        allowed = set()
        for product in products:
            allowed.add(round(product.base_price))
            for sku in product.skus:
                allowed.add(round(sku.price))
        if constraints.max_price is not None:
            allowed.add(round(constraints.max_price))
        if constraints.min_price is not None:
            allowed.add(round(constraints.min_price))

        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:元|块|RMB|rmb)", text):
            value = round(float(match.group(1)))
            if value not in allowed:
                return True
        return False

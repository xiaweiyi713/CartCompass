from __future__ import annotations

import re


PRICE_PATTERN = re.compile(r"(?:￥|¥|RMB|CNY|\$)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)


def parse_price(value: str | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    normalized = value.replace(",", "")
    matches = PRICE_PATTERN.findall(normalized)
    prices = [float(match) for match in matches]
    return min(prices) if prices else 0.0

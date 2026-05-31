from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from data_pipeline.cleaners.price_parser import parse_price
from data_pipeline.enrichers.attribute_tagger import build_review_summary, enrich_attributes
from data_pipeline.enrichers.category_mapper import map_category


DEFAULT_CURRENCY_RATES_TO_CNY = {
    "CNY": 1.0,
    "RMB": 1.0,
    "USD": 6.8,
}


def normalize_products(
    raw_items: list[dict[str, Any]],
    product_prefix: str = "p_collected",
    currency_rates_to_cny: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    rates = currency_rates_to_cny or DEFAULT_CURRENCY_RATES_TO_CNY
    for index, item in enumerate(raw_items, start=1):
        product = normalize_product(item, index, product_prefix, rates)
        if not product["title"] or not product["base_price"]:
            continue
        while product["product_id"] in seen_ids:
            product["product_id"] = f'{product["product_id"]}_{len(seen_ids) + 1}'
        seen_ids.add(product["product_id"])
        products.append(product)
    return products


def normalize_product(
    item: dict[str, Any],
    index: int,
    product_prefix: str = "p_collected",
    currency_rates_to_cny: dict[str, float] | None = None,
) -> dict[str, Any]:
    title = _pick(item, "title", "name")
    description = _pick(item, "description")
    brand = _pick(item, "brand") or _source_brand(item) or _guess_brand(title)
    source_price = parse_price(item.get("price") or item.get("price_text"))
    source_currency = (_pick(item, "price_currency") or "CNY").upper()
    exchange_rate_to_cny = _exchange_rate_to_cny(source_currency, currency_rates_to_cny)
    price = round(source_price * exchange_rate_to_cny, 2)
    category, sub_category = map_category(_pick(item, "source_category", "category"), _pick(item, "source_sub_category", "sub_category"), f"{title} {description}")
    product_id = item.get("product_id") or _stable_product_id(product_prefix, item, index)
    attributes = enrich_attributes(title, description)
    review_summary = build_review_summary(description)
    marketing = _marketing_description(title, brand, description, attributes, item.get("product_url", ""))

    return {
        "product_id": product_id,
        "title": title,
        "brand": brand,
        "category": category,
        "sub_category": sub_category,
        "base_price": price,
        "price_currency": "CNY",
        "source_price": source_price,
        "source_price_currency": source_currency,
        "exchange_rate_to_cny": exchange_rate_to_cny,
        "image_url": _pick(item, "image_url"),
        "product_url": _pick(item, "product_url"),
        "stock_status": item.get("stock_status", "unknown"),
        "rating": parse_price(item.get("rating")),
        "review_count": int(parse_price(item.get("review_count"))),
        "attributes": attributes,
        "review_summary": review_summary,
        "skus": [
            {
                "sku_id": f"s_{product_id}_1",
                "properties": {"来源": _pick(item, "source") or "公开页面采集"},
                "price": price,
            }
        ],
        "rag_knowledge": {
            "marketing_description": f"{marketing} 原站价格：{source_price:.2f} {source_currency}，按 1 {source_currency} = {exchange_rate_to_cny:.4f} CNY 清洗换算为约 {price:.2f} 元人民币。",
            "official_faq": _build_faq(title, brand, item, attributes),
            "user_reviews": _build_reviews(review_summary),
        },
    }


def load_raw_products(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("products"), list):
        return data["products"]
    if not isinstance(data, list):
        raise ValueError("raw product file must be a list or contain products: []")
    return data


def write_clean_products(
    raw_path: Path,
    output_path: Path,
    product_prefix: str = "p_collected",
    currency_rates_to_cny: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    products = normalize_products(load_raw_products(raw_path), product_prefix, currency_rates_to_cny)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    return products


def _pick(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None:
            text = " ".join(str(value).split())
            if text:
                return text
    return ""


def _guess_brand(title: str) -> str:
    if not title:
        return "未知品牌"
    token = re.split(r"[\s｜|/-]", title, maxsplit=1)[0]
    return token[:20] or "未知品牌"


def _exchange_rate_to_cny(currency: str, overrides: dict[str, float] | None) -> float:
    rates = DEFAULT_CURRENCY_RATES_TO_CNY | (overrides or {})
    if currency not in rates:
        return 1.0
    return float(rates[currency])


def _source_brand(item: dict[str, Any]) -> str:
    source = _pick(item, "source")
    if not source:
        return ""
    return source.replace("_", " ").title()


def _stable_product_id(prefix: str, item: dict[str, Any], index: int) -> str:
    basis = f"{item.get('product_url', '')}|{item.get('name', '')}|{index}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{index:03d}_{digest}"


def _marketing_description(title: str, brand: str, description: str, attributes: dict[str, list[str]], product_url: str) -> str:
    tags = "、".join(attributes.get("tags", [])[:8])
    headline = title if title.lower().startswith(brand.lower()) else f"{brand} {title}".strip()
    parts = [headline]
    if description:
        parts.append(description)
    if tags:
        parts.append(f"规则标签：{tags}。")
    if product_url:
        parts.append(f"公开来源链接：{product_url}")
    return " ".join(parts)


def _build_faq(title: str, brand: str, item: dict[str, Any], attributes: dict[str, list[str]]) -> list[dict[str, str]]:
    tags = "、".join(attributes.get("tags", [])[:6]) or "暂无明显标签"
    source = _pick(item, "source") or "公开页面"
    return [
        {
            "question": f"{title} 的主要推荐理由是什么？",
            "answer": f"根据采集到的公开商品信息，{brand} 这款商品的可用标签包括：{tags}。实际推荐时仍应结合预算、场景和排除条件。"
        },
        {
            "question": "这条商品数据来自哪里？",
            "answer": f"该补充数据来自 {source} 的公开页面采集，采集器遵守 robots.txt、低频请求，不包含登录态、验证码绕过或用户隐私信息。"
        },
    ]


def _build_reviews(summary: dict[str, list[str]]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    if summary["positive"]:
        reviews.append({"nickname": "规则摘要", "rating": 4, "content": "正向要点：" + "、".join(summary["positive"])})
    if summary["negative"]:
        reviews.append({"nickname": "规则摘要", "rating": 2, "content": "潜在顾虑：" + "、".join(summary["negative"])})
    return reviews

from __future__ import annotations

import json
import re
from html import unescape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from .base_crawler import DEFAULT_USER_AGENT, CrawlTarget, RobotsGuard, absolute_url, polite_sleep, write_json


class StaticPageCrawler:
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: int = 12) -> None:
        self.headers = {"User-Agent": user_agent}
        self.timeout = timeout
        self.robots = RobotsGuard(user_agent)

    def crawl(self, targets: list[CrawlTarget]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for target in targets:
            for url in target.urls:
                if not self.robots.can_fetch(target.base_url, url):
                    print(f"Skip by robots.txt: {url}")
                    continue
                try:
                    html = self.fetch(url)
                    item = self.parse_product_page(html, url, target)
                    results.append(item)
                    print(f"OK: {url}")
                except Exception as exc:
                    print(f"Failed: {url} -> {exc}")
                polite_sleep(target.delay_seconds)
        return results

    def crawl_to_file(self, targets: list[CrawlTarget], output_path: Path) -> list[dict[str, Any]]:
        results = self.crawl(targets)
        write_json(output_path, results)
        return results

    def fetch(self, url: str) -> str:
        response = requests.get(url, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding
        return response.text

    def parse_product_page(self, html: str, url: str, target: CrawlTarget) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        jsonld = _extract_product_jsonld(soup)
        selectors = target.selectors

        name = _select_text(soup, selectors.get("name")) or _jsonld_value(jsonld, "name") or _meta(soup, "og:title") or _select_text(soup, "h1")
        brand = _select_text(soup, selectors.get("brand")) or _jsonld_brand(jsonld)
        price = _select_text(soup, selectors.get("price")) or _jsonld_offer_value(jsonld, "price")
        price_currency = _jsonld_offer_value(jsonld, "priceCurrency")
        description = (
            _select_text(soup, selectors.get("description"))
            or _jsonld_value(jsonld, "description")
            or _meta(soup, "description")
            or _meta(soup, "og:description")
        )
        image_url = (
            _select_attr(soup, selectors.get("image"), "src")
            or _jsonld_image(jsonld)
            or _meta(soup, "og:image")
            or _select_attr(soup, "img", "src")
        )
        rating = _select_text(soup, selectors.get("rating")) or _jsonld_aggregate_value(jsonld, "ratingValue")
        review_count = _select_text(soup, selectors.get("review_count")) or _jsonld_aggregate_value(jsonld, "reviewCount")

        return {
            "source": target.name,
            "source_category": target.category,
            "source_sub_category": target.sub_category,
            "name": _clean(name),
            "brand": _clean(brand),
            "price_text": _clean(price),
            "price_currency": _clean(price_currency),
            "description": _clean(description),
            "image_url": absolute_url(url, image_url),
            "product_url": url,
            "rating": _clean(rating),
            "review_count": _clean(review_count),
            "crawl_time": datetime.now(timezone.utc).isoformat(),
        }


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def _select_text(soup: BeautifulSoup, selector: str | None) -> str:
    if not selector:
        return ""
    node = soup.select_one(selector)
    return node.get_text(" ", strip=True) if node else ""


def _select_attr(soup: BeautifulSoup, selector: str | None, attr: str) -> str:
    if not selector:
        return ""
    node = soup.select_one(selector)
    if not node:
        return ""
    return str(node.get(attr) or node.get(f"data-{attr}") or "")


def _meta(soup: BeautifulSoup, name: str) -> str:
    selector = "property" if name.startswith("og:") else "name"
    node = soup.select_one(f'meta[{selector}="{name}"]')
    return str(node.get("content") or "") if node else ""


def _extract_product_jsonld(soup: BeautifulSoup) -> dict[str, Any]:
    for node in soup.select('script[type="application/ld+json"]'):
        text = node.string or node.get_text()
        if not text.strip():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        product = _find_product_node(data)
        if product:
            return product
    return {}


def _find_product_node(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        node_type = data.get("@type")
        if node_type == "Product" or (isinstance(node_type, list) and "Product" in node_type):
            return data
        for key in ("@graph", "itemListElement", "mainEntity"):
            found = _find_product_node(data.get(key))
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _find_product_node(item)
            if found:
                return found
    return {}


def _jsonld_value(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if isinstance(value, str):
        return value
    return ""


def _jsonld_brand(data: dict[str, Any]) -> str:
    brand = data.get("brand")
    if isinstance(brand, str):
        return brand
    if isinstance(brand, dict):
        return str(brand.get("name") or "")
    return ""


def _jsonld_image(data: dict[str, Any]) -> str:
    image = data.get("image")
    if isinstance(image, str):
        return image
    if isinstance(image, list) and image:
        return str(image[0])
    return ""


def _jsonld_offer_value(data: dict[str, Any], key: str) -> str:
    offers = data.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        return str(offers.get(key) or "")
    return ""


def _jsonld_aggregate_value(data: dict[str, Any], key: str) -> str:
    rating = data.get("aggregateRating")
    if isinstance(rating, dict):
        return str(rating.get(key) or "")
    return ""

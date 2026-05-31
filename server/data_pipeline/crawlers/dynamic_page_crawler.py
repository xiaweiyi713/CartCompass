from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base_crawler import DEFAULT_USER_AGENT, CrawlTarget, RobotsGuard, absolute_url, polite_sleep, write_json


class DynamicPageCrawler:
    """Optional Playwright crawler for public JavaScript-rendered pages."""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.user_agent = user_agent
        self.robots = RobotsGuard(user_agent)

    async def crawl(self, targets: list[CrawlTarget]) -> list[dict[str, Any]]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Dynamic crawling requires playwright. Install it only if you need JS-rendered pages.") from exc

        results: list[dict[str, Any]] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=self.user_agent)
            for target in targets:
                for url in target.urls:
                    if not self.robots.can_fetch(target.base_url, url):
                        print(f"Skip by robots.txt: {url}")
                        continue
                    try:
                        item = await self.parse_product_page(page, url, target)
                        results.append(item)
                        print(f"OK: {url}")
                    except Exception as exc:
                        print(f"Failed: {url} -> {exc}")
                    polite_sleep(target.delay_seconds)
            await browser.close()
        return results

    async def crawl_to_file(self, targets: list[CrawlTarget], output_path: Path) -> list[dict[str, Any]]:
        results = await self.crawl(targets)
        write_json(output_path, results)
        return results

    async def parse_product_page(self, page: Any, url: str, target: CrawlTarget) -> dict[str, Any]:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        selectors = target.selectors
        name = await _text(page, selectors.get("name", "h1"))
        brand = await _text(page, selectors.get("brand", ""))
        price = await _text(page, selectors.get("price", ".price"))
        description = await _text(page, selectors.get("description", ".description"))
        image = await _attr(page, selectors.get("image", "img"), "src")
        rating = await _text(page, selectors.get("rating", ""))
        review_count = await _text(page, selectors.get("review_count", ""))
        return {
            "source": target.name,
            "source_category": target.category,
            "source_sub_category": target.sub_category,
            "name": name,
            "brand": brand,
            "price_text": price,
            "description": description,
            "image_url": absolute_url(url, image),
            "product_url": url,
            "rating": rating,
            "review_count": review_count,
            "crawl_time": datetime.now(timezone.utc).isoformat(),
        }


async def _text(page: Any, selector: str) -> str:
    if not selector:
        return ""
    locator = page.locator(selector).first
    if await locator.count() == 0:
        return ""
    value = await locator.text_content()
    return " ".join((value or "").split())


async def _attr(page: Any, selector: str, attr: str) -> str:
    if not selector:
        return ""
    locator = page.locator(selector).first
    if await locator.count() == 0:
        return ""
    value = await locator.get_attribute(attr)
    return value or ""


def crawl_sync(targets: list[CrawlTarget], output_path: Path) -> list[dict[str, Any]]:
    return asyncio.run(DynamicPageCrawler().crawl_to_file(targets, output_path))

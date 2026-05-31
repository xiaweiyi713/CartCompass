from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

sys.path.append(str(Path(__file__).resolve().parents[1]))

from data_pipeline.crawlers.base_crawler import DEFAULT_USER_AGENT, RobotsGuard


@dataclass(frozen=True)
class SourcePlan:
    name: str
    base_url: str
    category: str
    sub_category: str
    sitemap_url: str
    limit: int
    include_terms: tuple[str, ...] = ("/products/",)
    exclude_terms: tuple[str, ...] = field(default_factory=tuple)


SOURCE_PLANS = [
    SourcePlan(
        name="anker_official_store",
        base_url="https://www.anker.com",
        category="数码电子",
        sub_category="充电设备",
        sitemap_url="https://www.anker.com/sitemap.xml",
        limit=50,
        exclude_terms=("gift", "refurbished", "replacement"),
    ),
    SourcePlan(
        name="colourpop_official_store",
        base_url="https://colourpop.com",
        category="美妆护肤",
        sub_category="彩妆",
        sitemap_url="https://colourpop.com/sitemap.xml",
        limit=25,
        exclude_terms=("gift-card", "e-gift"),
    ),
    SourcePlan(
        name="bliss_official_store",
        base_url="https://www.blissworld.com",
        category="美妆护肤",
        sub_category="护肤",
        sitemap_url="https://www.blissworld.com/sitemap.xml",
        limit=40,
        exclude_terms=("gift-card", "bundle"),
    ),
    SourcePlan(
        name="baleaf_official_store",
        base_url="https://www.baleaf.com",
        category="服饰运动",
        sub_category="运动服饰",
        sitemap_url="https://www.baleaf.com/sitemap.xml",
        limit=45,
        exclude_terms=("gift-card",),
    ),
    SourcePlan(
        name="vessi_official_store",
        base_url="https://vessi.com",
        category="服饰运动",
        sub_category="运动鞋",
        sitemap_url="https://vessi.com/sitemap.xml",
        limit=35,
        exclude_terms=("giftcard", "gift-card"),
    ),
    SourcePlan(
        name="goruck_official_store",
        base_url="https://www.goruck.com",
        category="服饰运动",
        sub_category="运动装备",
        sitemap_url="https://www.goruck.com/sitemap.xml",
        limit=35,
        exclude_terms=("gift-card", "patch", "sticker", "laces"),
    ),
    SourcePlan(
        name="lacolombe_official_store",
        base_url="https://www.lacolombe.com",
        category="食品饮料",
        sub_category="咖啡",
        sitemap_url="https://www.lacolombe.com/sitemap.xml",
        limit=24,
        exclude_terms=("gift-card",),
    ),
    SourcePlan(
        name="deathwishcoffee_official_store",
        base_url="https://www.deathwishcoffee.com",
        category="食品饮料",
        sub_category="咖啡",
        sitemap_url="https://www.deathwishcoffee.com/sitemap.xml",
        limit=6,
        exclude_terms=("gift-card",),
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a crawl config from public product sitemaps.")
    parser.add_argument("--output", type=Path, default=Path("server/data_pipeline/configs/crawl_targets.large_batch.yaml"))
    parser.add_argument("--delay-min", type=float, default=0.5)
    parser.add_argument("--delay-max", type=float, default=1.0)
    args = parser.parse_args()

    robots = RobotsGuard(DEFAULT_USER_AGENT)
    sources = []
    for plan in SOURCE_PLANS:
        urls = select_urls(plan, robots)
        print(f"{plan.name}: selected {len(urls)} urls")
        sources.append(
            {
                "name": plan.name,
                "base_url": plan.base_url,
                "category": plan.category,
                "sub_category": plan.sub_category,
                "delay_seconds": [args.delay_min, args.delay_max],
                "selectors": {
                    "name": "h1",
                    "price": "",
                    "description": "",
                    "image": "",
                    "rating": "",
                    "review_count": "",
                },
                "urls": urls,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump({"sources": sources}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"wrote {args.output}")


def select_urls(plan: SourcePlan, robots: RobotsGuard) -> list[str]:
    candidates: list[str] = []
    for url in collect_sitemap_urls(plan.sitemap_url):
        if not any(term in url for term in plan.include_terms):
            continue
        lower_url = url.lower()
        if any(term in lower_url for term in plan.exclude_terms):
            continue
        if urlparse(url).netloc and not robots.can_fetch(plan.base_url, url):
            continue
        candidates.append(url)
        if len(candidates) >= plan.limit:
            break
    return candidates


def collect_sitemap_urls(sitemap_url: str, depth: int = 0) -> list[str]:
    if depth > 2:
        return []
    response = requests.get(sitemap_url, timeout=15, headers={"User-Agent": DEFAULT_USER_AGENT})
    response.raise_for_status()
    root = ET.fromstring(response.content)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    node_name = root.tag.rsplit("}", maxsplit=1)[-1]
    locs = [node.text for node in root.findall(".//sm:loc", namespace) if node.text]
    if node_name == "sitemapindex":
        urls: list[str] = []
        for loc in locs:
            if "product" in loc.lower():
                urls.extend(collect_sitemap_urls(loc, depth + 1))
        return urls
    return locs


if __name__ == "__main__":
    main()

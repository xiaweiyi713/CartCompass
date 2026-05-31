from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser


DEFAULT_USER_AGENT = "ShopGuideResearchBot/0.1 (+academic demo; contact: your_email@example.com)"


@dataclass(frozen=True)
class CrawlTarget:
    name: str
    base_url: str
    category: str = ""
    sub_category: str = ""
    urls: list[str] = field(default_factory=list)
    selectors: dict[str, str] = field(default_factory=dict)
    delay_seconds: tuple[float, float] = (1.5, 4.0)


class RobotsGuard:
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.user_agent = user_agent
        self._cache: dict[str, RobotFileParser | None] = {}

    def can_fetch(self, base_url: str, target_url: str) -> bool:
        parser = self._parser(base_url)
        if parser is None:
            return False
        return parser.can_fetch(self.user_agent, target_url)

    def _parser(self, base_url: str) -> RobotFileParser | None:
        if base_url in self._cache:
            return self._cache[base_url]
        parser = RobotFileParser()
        parser.set_url(urljoin(base_url, "/robots.txt"))
        try:
            parser.read()
        except Exception:
            self._cache[base_url] = None
            return None
        self._cache[base_url] = parser
        return parser


def load_targets(path: Path) -> list[CrawlTarget]:
    data = _load_config(path)
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("crawl config must contain a list field: sources")

    targets: list[CrawlTarget] = []
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("each source must be an object")
        delay = item.get("delay_seconds", [1.5, 4.0])
        urls = item.get("urls", [])
        if not item.get("name") or not item.get("base_url") or not urls:
            raise ValueError("each source requires name, base_url and urls")
        targets.append(
            CrawlTarget(
                name=str(item["name"]),
                base_url=str(item["base_url"]),
                category=str(item.get("category", "")),
                sub_category=str(item.get("sub_category", "")),
                urls=[str(url) for url in urls],
                selectors={str(k): str(v) for k, v in item.get("selectors", {}).items()},
                delay_seconds=(float(delay[0]), float(delay[1])),
            )
        )
    return targets


def polite_sleep(delay_seconds: tuple[float, float]) -> None:
    low, high = delay_seconds
    time.sleep(random.uniform(low, high))


def absolute_url(base_url: str, maybe_url: str | None) -> str:
    if not maybe_url:
        return ""
    return urljoin(base_url, maybe_url.strip())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("YAML config requires PyYAML. Install server/requirements.txt first.") from exc
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError("crawl config must be a YAML/JSON object")
    return loaded

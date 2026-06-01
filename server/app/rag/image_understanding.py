from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

from app.config import (
    VISION_UNDERSTANDING_API_KEY,
    VISION_UNDERSTANDING_BASE_URL,
    VISION_UNDERSTANDING_IMAGE_DETAIL,
    VISION_UNDERSTANDING_JSON_MODE,
    VISION_UNDERSTANDING_MAX_IMAGE_SIDE,
    VISION_UNDERSTANDING_MAX_TOKENS,
    VISION_UNDERSTANDING_MODEL,
    VISION_UNDERSTANDING_TIMEOUT_SECONDS,
)


ALLOWED_CATEGORIES = {"美妆护肤", "数码电子", "服饰运动", "食品饮料"}
CATEGORY_ALIASES = {
    "数码": "数码电子",
    "电子产品": "数码电子",
    "数码产品": "数码电子",
    "数码配件": "数码电子",
    "数码充电配件": "数码电子",
    "充电配件": "数码电子",
    "手机配件": "数码电子",
    "美妆": "美妆护肤",
    "护肤": "美妆护肤",
    "护肤品": "美妆护肤",
    "服饰": "服饰运动",
    "运动户外": "服饰运动",
    "户外运动": "服饰运动",
    "食品": "食品饮料",
    "饮品": "食品饮料",
}
ALLOWED_SUB_CATEGORIES = {
    "智能手机",
    "手机",
    "蓝牙耳机",
    "耳机",
    "充电设备",
    "充电器",
    "充电宝",
    "防晒",
    "面霜",
    "精华",
    "帽子",
    "背包",
    "徒步鞋",
    "咖啡",
    "零食",
    "饮料",
}
SUB_CATEGORY_ALIASES = {
    "双口usb-c pd快充墙充": "充电设备",
    "usb-c pd快充墙充": "充电设备",
    "快充墙充": "充电设备",
    "墙充": "充电设备",
    "电源适配器": "充电设备",
    "充电头": "充电设备",
    "快充头": "充电设备",
    "移动电源": "充电宝",
    "无线耳机": "蓝牙耳机",
    "真无线耳机": "蓝牙耳机",
    "智能机": "智能手机",
    "防晒霜": "防晒",
    "防晒乳": "防晒",
    "通勤包": "背包",
    "双肩包": "背包",
    "登山鞋": "徒步鞋",
}
BLOCKED_FACT_TERMS = (
    "价格",
    "元",
    "库存",
    "现货",
    "优惠",
    "折扣",
    "券",
    "销量",
    "包邮",
)


@dataclass(frozen=True)
class ImageUnderstandingResult:
    category: str | None = None
    sub_category: str | None = None
    keywords: list[str] | None = None
    attributes: list[str] | None = None
    confidence: float = 0.0
    provider: str = "disabled"
    available: bool = False

    @property
    def terms(self) -> list[str]:
        values: list[str] = []
        for value in [self.category, self.sub_category]:
            if value:
                values.append(value)
        values.extend(self.keywords or [])
        values.extend(self.attributes or [])
        return _dedupe_terms(values)


class OptionalVisionImageUnderstanding:
    """Optional OpenAI-compatible VLM adapter for image-to-shopping intent.

    The core service must run without a vision model. When no model/key is
    configured, this adapter returns an explicit unavailable result and image
    search keeps using CLIP/lightweight visual features.
    """

    def __init__(
        self,
        base_url: str = VISION_UNDERSTANDING_BASE_URL,
        model: str = VISION_UNDERSTANDING_MODEL,
        api_key: str = VISION_UNDERSTANDING_API_KEY,
        timeout_seconds: float = VISION_UNDERSTANDING_TIMEOUT_SECONDS,
        image_detail: str = VISION_UNDERSTANDING_IMAGE_DETAIL,
        max_image_side: int = VISION_UNDERSTANDING_MAX_IMAGE_SIDE,
        max_tokens: int = VISION_UNDERSTANDING_MAX_TOKENS,
        json_mode: bool = VISION_UNDERSTANDING_JSON_MODE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.image_detail = image_detail
        self.max_image_side = max(320, max_image_side)
        self.max_tokens = max(64, max_tokens)
        self.json_mode = json_mode
        self.provider = f"openai_compatible_vlm:{model}" if model else "disabled"
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def analyze(self, image: Image.Image, query: str = "") -> ImageUnderstandingResult:
        self.last_error = None
        if not self.available:
            self.last_error = "vision understanding is not configured"
            return ImageUnderstandingResult(provider=self.provider, available=False)
        try:
            payload = self._payload(image, query)
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return self._parse(content)
        except httpx.HTTPStatusError as exc:
            self.last_error = self._http_error_summary(exc.response)
            return ImageUnderstandingResult(provider=self.provider, available=False)
        except httpx.HTTPError as exc:
            self.last_error = f"http_error:{exc.__class__.__name__}"
            return ImageUnderstandingResult(provider=self.provider, available=False)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = f"parse_error:{exc.__class__.__name__}"
            return ImageUnderstandingResult(provider=self.provider, available=False)

    def _http_error_summary(self, response: httpx.Response) -> str:
        text = response.text[:400] if response.text else ""
        text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]+", r"\1***", text)
        return f"http_status:{response.status_code}:{text}"

    def _payload(self, image: Image.Image, query: str) -> dict[str, Any]:
        data_uri = self._data_uri(image)
        user_text = query.strip() or "请只根据图片判断适合电商找货的品类、子类目、商品关键词和外观属性。"
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是电商图片理解模块，只输出 JSON。"
                        "category 必须从 美妆护肤/数码电子/服饰运动/食品饮料 中选择或为空；"
                        "sub_category 只写商品库常见子类目；keywords 和 attributes 各不超过 6 个短词。"
                        "不要编造具体商品 ID、价格、库存、优惠、销量或平台政策。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": self._image_url_payload(data_uri)},
                    ],
                },
            ],
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _image_url_payload(self, data_uri: str) -> dict[str, str]:
        payload = {"url": data_uri}
        if self.image_detail in {"low", "high", "auto"}:
            payload["detail"] = self.image_detail
        return payload

    def _data_uri(self, image: Image.Image) -> str:
        buffer = io.BytesIO()
        self._resized(image).convert("RGB").save(buffer, format="JPEG", quality=86)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def _resized(self, image: Image.Image) -> Image.Image:
        rgb = image.convert("RGB")
        longest = max(rgb.size)
        if longest <= self.max_image_side:
            return rgb
        ratio = self.max_image_side / longest
        size = (max(1, int(rgb.width * ratio)), max(1, int(rgb.height * ratio)))
        return rgb.resize(size)

    def _parse(self, content: str) -> ImageUnderstandingResult:
        payload = _loads_json_object(content)
        category = _normalize_category(payload.get("category"))
        sub_category = _normalize_sub_category(payload.get("sub_category"))
        keywords = _clean_terms(payload.get("keywords"))
        attributes = _clean_terms(payload.get("attributes"))
        category, sub_category = _repair_taxonomy(category, sub_category, keywords + attributes)
        confidence = _clamp_float(payload.get("confidence"), default=0.6)
        available = bool(category or sub_category or keywords or attributes)
        return ImageUnderstandingResult(
            category=category,
            sub_category=sub_category,
            keywords=keywords,
            attributes=attributes,
            confidence=confidence,
            provider=self.provider,
            available=available,
        )


def _loads_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    if not text.startswith("{"):
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("vision result is not a JSON object")
        text = match.group(0)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("vision result is not a JSON object")
    return payload


def _clean_terms(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_terms(_clean_text(item) for item in value)


def _normalize_category(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if text in ALLOWED_CATEGORIES:
        return text
    lowered = text.lower()
    for alias, category in CATEGORY_ALIASES.items():
        if alias.lower() in lowered:
            return category
    return None


def _normalize_sub_category(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if text in ALLOWED_SUB_CATEGORIES:
        return text
    lowered = text.lower()
    for alias, sub_category in SUB_CATEGORY_ALIASES.items():
        if alias.lower() in lowered:
            return sub_category
    for allowed in ALLOWED_SUB_CATEGORIES:
        if allowed.lower() in lowered:
            return allowed
    return None


def _repair_taxonomy(
    category: str | None,
    sub_category: str | None,
    terms: list[str],
) -> tuple[str | None, str | None]:
    text = " ".join(terms).lower()
    charging_markers = ("充电", "快充", "墙充", "usb-c", "type-c", "pd", "gan", "电源适配器")
    if any(marker in text for marker in charging_markers):
        return category or "数码电子", "充电设备"
    phone_markers = ("手机", "iphone", "安卓", "摄像头", "屏幕", "续航")
    if sub_category is None and any(marker in text for marker in phone_markers):
        return category or "数码电子", "智能手机"
    sunscreen_markers = ("防晒", "spf", "pa++++", "隔离")
    if any(marker in text for marker in sunscreen_markers):
        return category or "美妆护肤", "防晒"
    return category, sub_category


def _dedupe_terms(values: Any) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        terms.append(text)
        if len(terms) >= 12:
            break
    return terms


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"[\s,，;；]+", " ", value).strip()
    if not text or len(text) > 24:
        return None
    if any(term in text for term in BLOCKED_FACT_TERMS):
        return None
    return text


def _clamp_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))

from __future__ import annotations

import re

from app.rag.product_repository import SearchConstraints


CATEGORY_KEYWORDS = {
    "美妆护肤": ["护肤", "美妆", "面霜", "精华", "防晒", "防晒乳", "洗面奶", "眼霜", "卸妆", "粉底", "蜜粉", "彩妆", "油皮"],
    "数码电子": ["手机", "耳机", "平板", "电脑", "笔记本", "数码", "拍照", "续航", "蓝牙", "充电器", "充电宝", "快充"],
    "服饰运动": ["衣服", "服饰", "跑鞋", "篮球鞋", "外套", "t恤", "穿搭", "背包", "运动", "运动裤", "速干", "户外", "防晒衣", "瑜伽裤", "短裤", "三亚", "海边", "度假", "旅行"],
    "食品饮料": ["食品", "饮料", "咖啡", "冷萃", "拿铁", "咖啡豆", "零食", "方便面", "能量", "气泡水", "坚果"],
}

SUBCATEGORY_KEYWORDS = [
    "防晒",
    "面霜",
    "精华",
    "眼霜",
    "卸妆",
    "洗面奶",
    "智能手机",
    "手机",
    "蓝牙耳机",
    "耳机",
    "充电宝",
    "充电器",
    "平板电脑",
    "平板",
    "笔记本电脑",
    "笔记本",
    "运动裤",
    "运动服饰",
    "运动鞋",
    "跑步鞋",
    "跑鞋",
    "篮球鞋",
    "短袖T恤",
    "外套",
    "冷萃",
    "拿铁",
    "咖啡",
    "方便食品",
    "功能饮料",
    "坚果",
]

NEGATIVE_PREFIXES = ("不要", "不含", "不想要", "别要", "除了", "排除")
BRANDS = ["耐克", "nike", "日系", "苹果", "apple", "华为", "小米", "adidas", "阿迪达斯", "oppo", "vivo"]


class ConstraintParser:
    def parse(self, message: str) -> SearchConstraints:
        normalized = self._normalize_message(message)
        constraints = SearchConstraints()
        constraints.category = self._category(normalized)
        constraints.sub_category = self._sub_category(normalized, constraints.category)
        constraints.max_price = self._max_price(normalized)
        constraints.min_price = self._min_price(normalized)
        constraints.exclude_terms = self._exclude_terms(normalized)
        constraints.exclude_brands = self._exclude_brands(normalized)
        constraints.include_terms = self._include_terms(normalized, constraints.exclude_terms)
        return constraints

    def merge(self, previous: SearchConstraints, current: SearchConstraints) -> SearchConstraints:
        if current.category and previous.category and current.category != previous.category:
            return current
        return SearchConstraints(
            category=current.category or previous.category,
            sub_category=current.sub_category or previous.sub_category,
            max_price=current.max_price if current.max_price is not None else previous.max_price,
            min_price=current.min_price if current.min_price is not None else previous.min_price,
            include_terms=list(dict.fromkeys(previous.include_terms + current.include_terms)),
            exclude_terms=list(dict.fromkeys(previous.exclude_terms + current.exclude_terms)),
            exclude_brands=list(dict.fromkeys(previous.exclude_brands + current.exclude_brands)),
        )

    def _category(self, message: str) -> str | None:
        lower = message.lower()
        scored = [
            (sum(1 for keyword in keywords if keyword in lower), category)
            for category, keywords in CATEGORY_KEYWORDS.items()
        ]
        score, category = max(scored, key=lambda item: item[0])
        if score:
            return category
        return None

    def _sub_category(self, message: str, category: str | None) -> str | None:
        lower = message.lower()
        if category == "服饰运动":
            if any(term in lower for term in ["运动裤", "速干", "户外", "瑜伽裤", "短裤", "防晒衣"]):
                return "运动服饰"
            if any(term in lower for term in ["跑鞋", "运动鞋", "篮球鞋", "鞋"]):
                return "运动鞋"
        if category == "食品饮料" and any(term in lower for term in ["咖啡", "冷萃", "拿铁", "咖啡豆"]):
            return "咖啡"
        if category == "数码电子":
            if "充电宝" in lower:
                return "充电宝"
            if "充电器" in lower or "快充" in lower:
                return "充电器"
        for keyword in SUBCATEGORY_KEYWORDS:
            if keyword.lower() in lower:
                return keyword
        return None

    def _max_price(self, message: str) -> float | None:
        approx = self._approx_price(message)
        if approx is not None:
            return approx * 1.35
        patterns = [
            r"(\d+(?:\.\d+)?)\s*(?:元|块|rmb)?\s*(?:以内|以下|内|之内)",
            r"预算\s*(\d+(?:\.\d+)?)",
            r"不超过\s*(\d+(?:\.\d+)?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.I)
            if match:
                return float(match.group(1))
        if re.fullmatch(r"\s*\d{3,6}(?:\.\d+)?\s*", message):
            return float(message.strip())
        return None

    def _min_price(self, message: str) -> float | None:
        approx = self._approx_price(message)
        if approx is not None:
            return approx * 0.65
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|rmb)?\s*(?:以上|起)", message, re.I)
        return float(match.group(1)) if match else None

    def _approx_price(self, message: str) -> float | None:
        price_value = r"(\d{1,6}(?:\.\d+)?\s*(?:k|K|千|万)?|[一二两三四五六七八九十]+(?:千|万)?)"
        patterns = [
            price_value + r"\s*(?:元|块|rmb)?\s*(?:左右|上下|附近|价位|档)",
            r"(?:要|想要|预算|价位)\s*" + price_value + r"\s*(?:元|块|rmb)?\s*(?:左右|上下|附近)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.I)
            if match:
                value = self._price_value(match.group(1))
                if value is not None:
                    return value
        return None

    def _price_value(self, raw: str) -> float | None:
        text = re.sub(r"\s+", "", raw).lower()
        match = re.fullmatch(r"(\d{1,6}(?:\.\d+)?)(k|千|万)?", text)
        if match:
            number = float(match.group(1))
            unit = match.group(2)
            if unit in {"k", "千"}:
                return number * 1000
            if unit == "万":
                return number * 10000
            return number
        chinese_digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        if text.endswith("千") and len(text) >= 2:
            prefix = text[:-1]
            if prefix in chinese_digits:
                return float(chinese_digits[prefix] * 1000)
        if text.endswith("万") and len(text) >= 2:
            prefix = text[:-1]
            if prefix in chinese_digits:
                return float(chinese_digits[prefix] * 10000)
        if text in chinese_digits:
            value = chinese_digits[text]
            return float(value * 1000 if value < 20 else value)
        return None

    def _exclude_terms(self, message: str) -> list[str]:
        terms: list[str] = []
        for prefix in NEGATIVE_PREFIXES:
            for match in re.finditer(prefix + r"([\u4e00-\u9fa5A-Za-z0-9]+)", message, re.I):
                raw = match.group(1).strip("的了吧呀，。；;、 ")
                term = self._brand_in_text(raw) or raw
                if term.startswith("含") and len(term) > 1:
                    term = term[1:]
                if term:
                    terms.append(term)
        if "酒精" in message and any(prefix in message for prefix in NEGATIVE_PREFIXES):
            terms.append("酒精")
        for ingredient in ["酒精", "香精", "水杨酸", "A醇", "精油"]:
            if f"无{ingredient}" in message:
                terms.append(ingredient)
        return list(dict.fromkeys(terms))

    def _exclude_brands(self, message: str) -> list[str]:
        brands = []
        lower = message.lower()
        for prefix in NEGATIVE_PREFIXES:
            for match in re.finditer(prefix + r"([\u4e00-\u9fa5A-Za-z0-9]+)", lower, re.I):
                brand = self._brand_in_text(match.group(1))
                if brand:
                    brands.append(brand)
        return list(dict.fromkeys(brands))

    def _brand_in_text(self, text: str) -> str:
        lower = text.lower()
        for brand in BRANDS:
            if brand in lower:
                return brand
        return ""

    def _normalize_message(self, message: str) -> str:
        normalized = message
        lower = re.sub(r"\s+", "", message.lower())
        iphone_aliases = ["17pm", "17promax", "iphone17pm", "iphone17promax", "苹果17pm", "苹果17promax"]
        if any(alias in lower for alias in iphone_aliases):
            normalized += " iPhone 17 Pro Max 苹果手机"
        elif re.search(r"(?<!\d)17\s*pro\s*max", message, re.I):
            normalized += " iPhone 17 Pro Max 苹果手机"
        elif re.search(r"(?<!\d)17\s*pro(?!\s*max)", message, re.I):
            normalized += " iPhone 17 Pro 苹果手机"
        return normalized

    def _include_terms(self, message: str, excluded: list[str]) -> list[str]:
        candidates = [
            "油皮",
            "敏感肌",
            "保湿",
            "补水",
            "轻量",
            "快充",
            "充电宝",
            "iPhone",
            "Pro Max",
            "拍照",
            "影像",
            "续航",
            "游戏",
            "性能",
            "性价比",
            "低糖",
            "无糖",
            "透气",
            "咖啡",
            "冷萃",
            "拿铁",
            "苹果",
            "Apple",
            "iPhone",
            "华为",
            "小米",
            "OPPO",
            "vivo",
        ]
        return [term for term in candidates if term in message and term not in excluded]

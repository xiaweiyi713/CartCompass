from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from app.config import STORAGE_DIR
from app.models.schemas import UserProfile
from app.rag.product_repository import SearchConstraints
from app.agent.travel_intent import parse_travel_context


PROFILE_PATH = STORAGE_DIR / "user_profiles.json"
SAVE_LOCK = threading.RLock()


class UserProfileService:
    def __init__(self, path: Path = PROFILE_PATH) -> None:
        self.path = path
        self._profiles: dict[str, UserProfile] = {}
        self._load()

    def get(self, user_id: str) -> UserProfile:
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile(user_id=user_id)
        return self._profiles[user_id]

    def clear(self, user_id: str) -> UserProfile:
        self._profiles[user_id] = UserProfile(user_id=user_id)
        self._save()
        return self._profiles[user_id]

    def remember_from_message(self, user_id: str, message: str) -> tuple[UserProfile, list[str]]:
        profile = self.get(user_id)
        updates: list[str] = []
        category = self._profile_category(message)
        budget = self._budget(message)
        if category and budget is not None:
            profile.budget_preferences[category] = budget
            updates.append(f"{category}预算约 {budget:.0f} 元")

        skin_type = self._skin_type(message)
        if skin_type:
            profile.skin_type = skin_type
            updates.append(f"肤质：{skin_type}")

        for brand in self._excluded_brands(message):
            if brand not in profile.excluded_brands:
                profile.excluded_brands.append(brand)
                updates.append(f"排除品牌：{brand}")

        for ingredient in self._excluded_ingredients(message):
            if ingredient not in profile.excluded_ingredients:
                profile.excluded_ingredients.append(ingredient)
                updates.append(f"排除成分：{ingredient}")

        for feature in self._preferred_features(message):
            if feature not in profile.preferred_features:
                profile.preferred_features.append(feature)
                updates.append(f"偏好：{feature}")

        travel = parse_travel_context(message)
        if travel.is_travel:
            scenario = f"{travel.destination}/{travel.scenario}"
            if scenario not in profile.travel_scenario:
                profile.travel_scenario.append(scenario)
                updates.append(f"场景：{scenario}")

        if updates:
            self._save()
        return profile, updates

    def remember_scenario_from_message(self, user_id: str, message: str) -> tuple[UserProfile, list[str]]:
        profile = self.get(user_id)
        updates: list[str] = []
        travel = parse_travel_context(message)
        if travel.is_travel:
            scenario = f"{travel.destination}/{travel.scenario}"
            if scenario not in profile.travel_scenario:
                profile.travel_scenario.append(scenario)
                updates.append(f"场景：{scenario}")
        for feature in self._preferred_features(message):
            if feature not in profile.preferred_features and feature in {"轻量", "防水", "防汗", "低糖", "无糖"}:
                profile.preferred_features.append(feature)
                updates.append(f"偏好：{feature}")
        if updates:
            self._save()
        return profile, updates

    def record_feedback(self, user_id: str, product_id: str, feedback: str, note: str = "") -> UserProfile:
        profile = self.get(user_id)
        profile.last_feedback.append({"product_id": product_id, "feedback": feedback, "note": note})
        profile.last_feedback = profile.last_feedback[-20:]
        self._save()
        return profile

    def apply_to_constraints(self, user_id: str, constraints: SearchConstraints, message: str = "") -> SearchConstraints:
        profile = self.get(user_id)
        category_key = self._budget_key_for_category(constraints.category)
        max_price = constraints.max_price
        if max_price is None and category_key and category_key in profile.budget_preferences:
            max_price = profile.budget_preferences[category_key]

        include_terms = list(dict.fromkeys(constraints.include_terms + profile.preferred_features[:4]))
        if constraints.category == "美妆护肤" and profile.skin_type and profile.skin_type not in include_terms:
            include_terms.append(profile.skin_type)
        profile_excluded_ingredients = self._profile_excluded_ingredients_for_message(
            profile.excluded_ingredients,
            message,
        )
        profile_excluded_brands = self._profile_excluded_brands_for_message(profile.excluded_brands, message)

        return SearchConstraints(
            category=constraints.category,
            sub_category=constraints.sub_category,
            max_price=max_price,
            min_price=constraints.min_price,
            include_terms=include_terms,
            exclude_terms=list(dict.fromkeys(constraints.exclude_terms + profile_excluded_ingredients)),
            exclude_brands=list(dict.fromkeys(constraints.exclude_brands + profile_excluded_brands)),
            exclude_product_ids=constraints.exclude_product_ids,
        )

    def _profile_excluded_brands_for_message(self, excluded_brands: list[str], message: str) -> list[str]:
        if not message:
            return excluded_brands
        return [brand for brand in excluded_brands if not self._explicitly_wants_brand(message, brand)]

    def _profile_excluded_ingredients_for_message(self, excluded_ingredients: list[str], message: str) -> list[str]:
        if not message:
            return excluded_ingredients
        return [
            ingredient
            for ingredient in excluded_ingredients
            if not self._explicitly_wants_ingredient(message, ingredient)
        ]

    def _explicitly_wants_brand(self, message: str, brand: str) -> bool:
        lower = re.sub(r"\s+", "", message.lower())
        negative_prefixes = ["不要", "不想要", "排除", "避开", "别要", "除了"]
        aliases = {
            "苹果": ["苹果", "apple", "iphone", "ipad", "macbook"],
            "apple": ["苹果", "apple", "iphone", "ipad", "macbook"],
            "小米": ["小米", "xiaomi"],
            "华为": ["华为", "huawei"],
            "oppo": ["oppo"],
            "vivo": ["vivo"],
            "耐克": ["耐克", "nike"],
            "nike": ["耐克", "nike"],
        }.get(brand.lower(), [brand.lower()])
        if not any(alias in lower for alias in aliases):
            return False
        return not any(prefix + alias in lower for prefix in negative_prefixes for alias in aliases)

    def _explicitly_wants_ingredient(self, message: str, ingredient: str) -> bool:
        lower = re.sub(r"\s+", "", message.lower())
        term = ingredient.lower()
        if term not in lower:
            return False
        negative_prefixes = ["不要", "不含", "无", "不想要", "排除", "避开", "别要", "不加", "不添加", "没有"]
        if any(prefix + term in lower or prefix + "含" + term in lower for prefix in negative_prefixes):
            return False
        positive_prefixes = ["要", "需要", "想要", "可以含", "可含", "能接受", "接受", "不介意", "含", "带", "有"]
        if any(prefix + term in lower for prefix in positive_prefixes):
            return True
        intent_words = ["推荐", "买", "找", "需要", "要", "喷雾", "湿巾", "消毒", "香水"]
        return any(word in lower for word in intent_words)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        self._profiles = {
            user_id: UserProfile(**profile)
            for user_id, profile in payload.items()
            if isinstance(profile, dict)
        }

    def _save(self) -> None:
        with SAVE_LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                user_id: profile.model_dump()
                for user_id, profile in self._profiles.items()
                if self._has_persisted_value(profile)
            }
            content = json.dumps(payload, ensure_ascii=False, indent=2)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                handle.write("\n")
                temp_name = handle.name
            os.replace(temp_name, self.path)

    def _has_persisted_value(self, profile: UserProfile) -> bool:
        return bool(
            profile.budget_preferences
            or profile.preferred_features
            or profile.excluded_brands
            or profile.excluded_ingredients
            or profile.skin_type
            or profile.travel_scenario
            or profile.last_feedback
        )

    def _budget(self, message: str) -> float | None:
        match = re.search(
            r"(?:预算|不超过|控制在|价位|价格|大概)\s*(\d+(?:\.\d+)?)\s*(?:元|块|rmb)?\s*(?:以内|以下|左右)?"
            r"|(\d+(?:\.\d+)?)\s*(?:元|块|rmb)\s*(?:以内|以下|左右|预算)?",
            message,
            re.I,
        )
        if not match:
            return None
        value = match.group(1) or match.group(2)
        return float(value) if value else None

    def _profile_category(self, message: str) -> str | None:
        if any(term in message for term in ["护肤", "防晒", "美妆"]):
            return "护肤品"
        if any(term in message for term in ["手机", "数码", "耳机", "电脑"]):
            return "数码"
        if any(term in message for term in ["咖啡", "零食", "饮料"]):
            return "食品饮料"
        if any(term in message for term in ["衣服", "服饰", "鞋", "运动"]):
            return "服饰运动"
        return None

    def _budget_key_for_category(self, category: str | None) -> str | None:
        mapping = {
            "美妆护肤": "护肤品",
            "数码电子": "数码",
            "食品饮料": "食品饮料",
            "服饰运动": "服饰运动",
        }
        return mapping.get(category or "")

    def _skin_type(self, message: str) -> str | None:
        for term in ["油皮", "干皮", "敏感肌", "混油皮", "混干皮"]:
            if term in message:
                return term
        return None

    def _excluded_brands(self, message: str) -> list[str]:
        brands = ["小米", "苹果", "Apple", "华为", "OPPO", "vivo", "耐克", "Nike", "日系"]
        if not any(term in message for term in ["不要", "不想要", "排除", "以后不买", "避开"]):
            return []
        lower = message.lower()
        return [brand for brand in brands if brand.lower() in lower]

    def _excluded_ingredients(self, message: str) -> list[str]:
        ingredients = ["酒精", "香精", "酸类", "水杨酸", "A醇", "精油"]
        if not any(term in message for term in ["不要", "不含", "避开", "排除", "以后"]):
            return []
        return [ingredient for ingredient in ingredients if ingredient in message]

    def _preferred_features(self, message: str) -> list[str]:
        features = [
            "拍照",
            "续航",
            "游戏",
            "性价比",
            "轻量",
            "快充",
            "低糖",
            "无糖",
            "控油",
            "保湿",
            "防水",
            "防汗",
        ]
        excluded = set(self._excluded_ingredients(message) + self._excluded_brands(message))
        return [feature for feature in features if feature in message and feature not in excluded]

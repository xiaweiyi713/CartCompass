from __future__ import annotations

import re


class IntentRules:
    def is_profile_remember(self, message: str) -> bool:
        compact = self.compact(message)
        return any(term in compact for term in ["记住", "以后", "下次"]) and any(
            term in compact for term in ["不要", "预算", "油皮", "干皮", "敏感肌", "偏好", "喜欢", "排除", "避开"]
        )

    def is_profile_view(self, message: str) -> bool:
        return self.compact(message) in {"查看我的偏好", "我的偏好", "看看我的偏好", "用户画像", "我的用户画像"}

    def is_profile_clear(self, message: str) -> bool:
        return self.compact(message) in {"清除我的偏好", "清空我的偏好", "删除我的偏好", "重置我的偏好", "清除我的所有偏好", "清空我的所有偏好"}

    def is_weather(self, message: str) -> bool:
        compact = self.compact(message).lower()
        return "天气" in compact and any(term in compact for term in ["今天", "明天", "现在", "怎么样", "如何", "适合出门", "适合户外"])

    def weather_location(self, message: str) -> str | None:
        compact = self.compact(message)
        compact = compact.replace("今天天气怎么样", "").replace("明天天气怎么样", "")
        compact = compact.replace("今天天气如何", "").replace("明天天气如何", "")
        compact = compact.replace("现在天气怎么样", "").replace("天气怎么样", "").replace("天气如何", "")
        compact = compact.replace("今天", "").replace("明天", "").replace("现在", "").strip()
        if not compact or compact in {"当地", "这里", "我这里"}:
            return None
        return compact

    def is_casual_no_preference(self, message: str) -> bool:
        return self.compact(message).lower() in {"随便", "都行", "不限", "你看着推荐", "看你推荐", "默认", "无所谓"}

    def is_vague_shopping(self, compact: str) -> bool:
        if len(compact) <= 2:
            return False
        vague_terms = [
            "礼物",
            "送人",
            "送女生",
            "送男生",
            "送朋友",
            "送女朋友",
            "送男朋友",
            "买点东西",
            "买个东西",
            "挑个东西",
            "推荐点东西",
            "随便推荐",
            "实用的",
        ]
        action_terms = ["买", "推荐", "挑", "选", "送"]
        return any(term in compact for term in vague_terms) and any(term in compact for term in action_terms)

    def is_gift(self, compact: str) -> bool:
        return any(
            term in compact
            for term in ["礼物", "送人", "送女生", "送男生", "送朋友", "送女朋友", "送男朋友", "生日", "纪念日"]
        )

    def has_enough_signal(self, constraints) -> bool:
        return bool(
            constraints.max_price is not None
            or constraints.min_price is not None
            or constraints.include_terms
            or constraints.exclude_terms
            or constraints.exclude_brands
        )

    def has_specific_product_signal(self, message: str, constraints) -> bool:
        compact = self.compact(message).lower()
        if any(term in compact for term in ["苹果", "apple", "iphone", "华为", "huawei", "小米", "xiaomi", "oppo", "vivo"]):
            return True
        if constraints.category == "数码电子" and constraints.sub_category in {"手机", "智能手机"}:
            if re.fullmatch(r"\d{2}", compact) or re.search(r"\d+\s*(?:pro|max|ultra|plus|pm)", compact, re.I):
                return True
        return False

    def is_broad_subcategory(self, sub_category: str | None, broad_values: list[str]) -> bool:
        return sub_category in broad_values

    def is_broad_message(self, compact: str) -> bool:
        return len(compact) <= 8 or compact in {"推荐衣服", "推荐运动", "推荐服饰", "推荐跑鞋"}

    def is_cart(self, message: str) -> bool:
        return any(word in message for word in ["购物车", "加购", "加入", "下单", "结算", "付款", "支付", "删除", "删掉", "清空", "数量", "改成"])

    def is_feedback(self, message: str, last_product_ids: list[str]) -> bool:
        if not last_product_ids:
            return False
        compact = self.compact(message)
        return any(term in compact for term in ["太贵", "便宜点", "平替", "高端", "升级", "换品牌", "换个品牌", "别的品牌", "不喜欢", "喜欢这款", "喜欢这个"])

    def is_more_results(self, message: str, last_product_ids: list[str]) -> bool:
        if not last_product_ids:
            return False
        compact = self.compact(message)
        return any(
            term in compact
            for term in [
                "再多几个",
                "多来几个",
                "多推荐几个",
                "还有吗",
                "还有没有",
                "再推荐几个",
                "再来几个",
                "继续推荐",
                "换几款",
                "换几个",
                "更多",
            ]
        )

    def is_affirmative_confirmation(self, message: str) -> bool:
        compact = self.compact(message)
        return compact in {"是", "是的", "对", "对的", "嗯", "嗯嗯", "没错", "对呀", "对啊", "是啊", "是呀"}

    def is_after_sale(self, message: str) -> bool:
        compact = self.compact(message)
        return any(term in compact for term in ["售后", "退换", "退货", "换货", "保修", "质保", "运费险", "七天无理由", "能退吗", "能换吗"])

    def feedback_type(self, message: str) -> str:
        compact = self.compact(message)
        if any(term in compact for term in ["喜欢这款", "喜欢这个", "不错", "可以"]):
            return "like"
        if any(term in compact for term in ["太贵", "便宜点", "平替", "预算低"]):
            return "too_expensive"
        if any(term in compact for term in ["高端", "升级", "更好", "贵一点"]):
            return "want_premium"
        if any(term in compact for term in ["换品牌", "换个品牌", "别的品牌", "不要这个品牌"]):
            return "change_brand"
        return "dislike"

    def is_compare(self, message: str) -> bool:
        if any(word in message for word in ["对比", "比较", "哪个更", "哪款更", "前两款"]):
            return True
        return "区别" in message and any(left in message for left in ["第一", "1"]) and any(right in message for right in ["第二", "2"])

    def is_product_qa(self, message: str, last_product_ids: list[str]) -> bool:
        if not last_product_ids:
            return False
        compact = self.compact(message).lower()
        reference_terms = ["这款", "这个", "它", "第一款", "第一个", "第二款", "第二个", "第三款", "第三个", "上一款"]
        qa_terms = [
            "为什么",
            "推荐理由",
            "差评",
            "低分",
            "缺点",
            "评论",
            "评价",
            "口碑",
            "来源",
            "真实",
            "可靠",
            "证据",
            "规格",
            "版本",
            "颜色",
            "容量",
            "尺码",
            "怎么选",
            "如何选",
            "区别",
            "有没有",
            "含不含",
            "适合",
            "防水",
            "防汗",
            "控油",
            "搓泥",
            "酒精",
            "敏感肌",
        ]
        has_reference = any(term in compact for term in reference_terms) or re.search(
            r"(?:第[123一二三](?:款|个)?|[123](?:款|个))", compact
        ) is not None
        has_question = any(term in compact for term in qa_terms)
        short_followup = compact in {"为什么", "差评呢", "评论呢", "可靠吗", "怎么选", "有酒精吗"}
        return (has_reference and has_question) or short_followup

    def target_product_id(self, message: str, last_product_ids: list[str]) -> str | None:
        if not last_product_ids:
            return None
        number_map = {"第一": 0, "第一个": 0, "1": 0, "第二": 1, "第二个": 1, "2": 1, "第三": 2, "第三个": 2, "3": 2}
        for word, idx in number_map.items():
            if word in message and idx < len(last_product_ids):
                return last_product_ids[idx]
        return last_product_ids[0]

    def quantity(self, message: str) -> int:
        match = re.search(r"(\d+)\s*(?:件|个|份|瓶|双|台)?", message)
        return max(1, int(match.group(1))) if match else 1

    def compact(self, message: str) -> str:
        return re.sub(r"[\s，。！？,.!?]", "", message)

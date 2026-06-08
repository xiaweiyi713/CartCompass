from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ConversationMode = Literal[
    "general_chat",
    "product_knowledge",
    "weather_query",
    "travel_weather_planning",
    "weak_purchase_intent",
    "shopping_assist",
    "transaction",
]


@dataclass(frozen=True)
class ConversationModeDecision:
    mode: ConversationMode
    shopping_intent_level: int
    need_rag: bool
    need_product_cards: bool
    need_tool_call: bool
    reason: str


class ConversationModeRouter:
    """Routes a message before product retrieval.

    The router deliberately uses deterministic rules. The model may help with
    language generation later, but routing must be stable enough to prevent
    accidental hard-selling on ordinary chat or knowledge questions.
    """

    def route(
        self,
        message: str,
        has_last_products: bool = False,
        has_pending_clarification: bool = False,
        has_active_shopping_context: bool = False,
    ) -> ConversationModeDecision:
        compact = self._compact(message)
        lower = message.lower()

        if self._is_transaction(compact):
            return ConversationModeDecision("transaction", 4, False, False, True, "购物车/结算/订单操作")
        if self._is_weather_shopping_request(compact):
            return ConversationModeDecision("travel_weather_planning", 3, True, True, False, "旅行/出行购物需要天气上下文")
        if self._is_weather_query(compact):
            return ConversationModeDecision("weather_query", 0, False, False, False, "实时天气查询")
        if self._is_feedback(compact, has_last_products):
            return ConversationModeDecision("shopping_assist", 3, True, True, False, "用户在反选上一轮商品")
        if self._is_more_results(compact, has_last_products):
            return ConversationModeDecision("shopping_assist", 3, True, True, False, "用户要求延续上一轮条件继续推荐")
        if self._is_product_followup_question(compact, has_last_products):
            return ConversationModeDecision("shopping_assist", 3, False, False, False, "用户在追问上一轮商品事实，交给商品 QA 链路")
        if self._is_medical_claim_request(compact):
            return ConversationModeDecision("product_knowledge", 1, False, False, False, "医疗功效/健康风险请求，不直接推荐商品")
        if self._is_strong_purchase(compact, lower):
            return ConversationModeDecision("shopping_assist", 3, True, True, False, "明确推荐、筛选、对比或购买意图")
        if (has_pending_clarification or has_active_shopping_context) and self._looks_like_clarification_answer(compact):
            return ConversationModeDecision("shopping_assist", 3, True, True, False, "用户在延续上一轮导购条件")
        if self._is_weak_purchase(compact):
            return ConversationModeDecision("weak_purchase_intent", 2, False, False, False, "存在潜在购买需求但目标不明确")
        if self._is_product_knowledge(compact, lower):
            return ConversationModeDecision("product_knowledge", 1, False, False, False, "商品/消费知识问题，无明确购买意图")
        return ConversationModeDecision("general_chat", 0, False, False, False, "普通对话或生活表达")

    def _compact(self, message: str) -> str:
        return re.sub(r"[\s，。！？,.!?；;：:、]+", "", message.lower())

    def _is_transaction(self, compact: str) -> bool:
        if any(term in compact for term in ["支付失败", "付款失败", "下单失败", "失败了怎么办", "支付不了怎么办"]):
            return False
        return any(term in compact for term in ["加入购物车", "加购", "下单", "去结算", "结算", "付款", "支付", "清空购物车", "购物车", "数量改", "改成"])

    def _is_product_followup_question(self, compact: str, has_last_products: bool) -> bool:
        if not has_last_products:
            return False
        reference = any(term in compact for term in ["这款", "这个", "这件", "它", "第一款", "第二款", "第三款", "上一款"])
        fact_question = any(
            term in compact
            for term in [
                "评论",
                "评价",
                "差评",
                "来源",
                "真实",
                "规格",
                "颜色",
                "容量",
                "尺码",
                "什么码",
                "选码",
                "售后",
                "保修",
                "退换",
                "为什么",
                "适合",
                "含不含",
                "兼容",
                "适配",
                "能用",
                "能不能用",
                "能给",
                "优惠",
                "满减",
                "活动",
                "多少钱",
                "价格",
            ]
        )
        storage_price = re.search(r"\d+\s*(?:g|gb|t|tb).*(?:多少钱|价格)", compact, re.I) is not None
        return (reference and fact_question) or storage_price

    def _is_feedback(self, compact: str, has_last_products: bool) -> bool:
        if not has_last_products:
            return False
        return any(
            term in compact
            for term in [
                "太贵",
                "便宜点",
                "平替",
                "高端",
                "升级",
                "换品牌",
                "换个品牌",
                "别的品牌",
                "不喜欢",
                "不要",
                "喜欢这款",
                "喜欢这个",
                "太商务",
                "年轻一点",
                "换个年轻",
                "换个",
            ]
        )

    def _is_more_results(self, compact: str, has_last_products: bool) -> bool:
        if not has_last_products:
            return False
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

    def _is_strong_purchase(self, compact: str, lower: str) -> bool:
        if self._is_campus_buy_request(compact):
            return True
        if self._is_travel_buy_request(compact):
            return True
        strong_terms = [
            "推荐",
            "想买",
            "我要买",
            "想入手",
            "帮我挑",
            "帮我看看",
            "看看",
            "怎么选",
            "哪个好",
            "哪款好",
            "对比",
            "比较",
            "平替",
            "升级款",
            "预算",
            "以内",
            "不超过",
            "适合我的",
            "适合油皮的",
            "适合敏感肌的",
            "买点",
            "挑个东西",
            "礼物",
            "送女生",
            "送男生",
            "实用的",
        ]
        if any(term in compact for term in strong_terms):
            return True
        product_terms = ["耳机", "充电", "充电宝", "防晒", "跑鞋", "背包", "零食", "饮料", "咖啡"]
        conversational_buy = any(term in compact for term in ["有没有", "有没有那种", "那种", "能安静", "能用", "好用"])
        if conversational_buy and any(term in compact for term in product_terms):
            return True
        # Specific product/model requests such as "17pm" or "iPhone 17 Pro".
        if re.search(r"(iphone|ipad|macbook|17\s*p\s*m|17pm|pro\s*max|小米\d+|oppo|vivo|huawei)", lower, re.I):
            return True
        if re.search(r"\d{2}\s*(?:pro|max|ultra|plus|pm)", lower, re.I):
            return True
        if any(term in compact for term in ["苹果", "华为", "小米", "荣耀", "一加", "三星", "oppo", "vivo"]):
            return any(term in compact for term in ["看", "要", "买", "推荐", "手机", "平板", "电脑", "不要"])
        return False

    def _is_medical_claim_request(self, compact: str) -> bool:
        medical_targets = ["失眠", "睡不着", "睡眠障碍", "焦虑", "抑郁", "膝盖疼", "疼痛"]
        cure_terms = ["治", "治疗", "治好", "治愈", "药", "处方", "保证"]
        return any(target in compact for target in medical_targets) and any(term in compact for term in cure_terms)

    def _looks_like_clarification_answer(self, compact: str) -> bool:
        if not compact:
            return False
        normalized = compact.strip("呢吗呀啊吧了")
        if re.fullmatch(r"\d{2,6}", normalized):
            return True
        if re.fullmatch(r"\d{3,6}的", normalized):
            return True
        if re.fullmatch(r"[一二两三四五六七八九十]+(?:千|万)(?:元|块|rmb)?", normalized, re.I):
            return True
        if re.search(r"(?:\d{1,6}(?:\.\d+)?(?:k|千|万)?|[一二两三四五六七八九十]+(?:千|万)?)(?:元|块|rmb)?(?:左右|上下|附近|价位|档)", normalized, re.I):
            return True
        if normalized in {"随便", "都行", "不限", "默认", "无所谓", "你看着推荐", "看你推荐", "是", "是的", "对", "对的", "嗯", "没错"}:
            return True
        return any(
            term in compact
            for term in [
                "拍照",
                "续航",
                "游戏",
                "性能",
                "性价比",
                "便宜",
                "高端",
                "护肤",
                "美妆",
                "数码",
                "服饰",
                "食品",
                "零食",
                "运动",
                "跑步",
                "通勤",
                "轻量",
                "轻一点",
                "轻便",
                "缓震",
                "户外",
                "油皮",
                "干皮",
                "敏感肌",
                "不要",
                "以内",
            ]
        )

    def _is_weak_purchase(self, compact: str) -> bool:
        if self._is_campus_buy_request(compact):
            return False
        if self._is_travel_buy_request(compact):
            return False
        weak_patterns = [
            "不知道买什么",
            "买什么好",
            "有什么东西",
            "有没有什么东西",
            "需要买什么",
            "需要准备什么",
            "想运动但不知道",
            "压力大有没有",
            "睡眠不好",
            "睡眠不太好",
            "睡眠差",
            "睡不好",
            "睡不着",
            "失眠",
            "入睡困难",
            "帮助睡眠",
            "改善睡眠",
            "缓解压力",
            "皮肤出油怎么办",
            "脸上出油怎么办",
        ]
        return any(term in compact for term in weak_patterns)

    def _is_campus_buy_request(self, compact: str) -> bool:
        campus_terms = [
            "上大学",
            "大学",
            "大学生",
            "开学",
            "入学",
            "返校",
            "校园",
            "宿舍",
            "寝室",
            "军训",
        ]
        buy_terms = [
            "买什么",
            "买点什么",
            "要买",
            "需要买",
            "需要准备",
            "准备什么",
            "带什么",
            "清单",
            "推荐",
            "配一套",
            "应该买",
        ]
        return any(term in compact for term in campus_terms) and any(term in compact for term in buy_terms)

    def _is_product_knowledge(self, compact: str, lower: str) -> bool:
        knowledge_terms = ["是什么", "什么意思", "区别", "原理", "怎么用", "有什么影响", "为什么", "解释一下", "科普"]
        product_terms = [
            "spf",
            "pa",
            "防晒",
            "油皮",
            "混油皮",
            "干皮",
            "敏感肌",
            "酒精",
            "香精",
            "a19",
            "芯片",
            "续航",
            "快充",
            "蓝牙",
            "降噪",
            "跑鞋",
            "缓震",
            "咖啡因",
        ]
        return any(term in compact for term in knowledge_terms) and any(term in lower or term in compact for term in product_terms)

    def _is_travel_buy_request(self, compact: str) -> bool:
        travel_terms = [
            "旅行",
            "旅游",
            "出差",
            "度假",
            "去三亚",
            "去日本",
            "去新疆",
            "去西藏",
            "去哈尔滨",
            "去成都",
            "去张家界",
            "海岛",
            "徒步",
            "自驾",
            "露营",
        ]
        buy_terms = ["买什么", "带什么", "准备什么", "准备东西", "帮我准备", "准备", "推荐", "配一套", "要带的东西", "应该买"]
        destination_pattern = "去" in compact and any(term in compact for term in ["玩", "旅行", "旅游", "度假", "徒步", "自驾", "露营"])
        return (any(term in compact for term in travel_terms) or destination_pattern) and any(term in compact for term in buy_terms)

    def _is_weather_query(self, compact: str) -> bool:
        if "天气" not in compact:
            return False
        if any(term in compact for term in ["真好", "不错", "很好", "好舒服", "太好了", "好晴朗"]):
            return False
        explicit_query_terms = ["怎么样", "如何", "冷吗", "热吗", "下雨", "会下雨", "多少度", "几度", "适合出门", "适合户外"]
        lookup_terms = ["查", "查一下", "看一下", "看看", "问一下", "问下"]
        return any(term in compact for term in explicit_query_terms + lookup_terms)

    def _is_weather_shopping_request(self, compact: str) -> bool:
        if "天气" not in compact and not any(term in compact for term in ["下雨", "冷吗", "热吗"]):
            return False
        return any(term in compact for term in ["买什么", "带什么", "准备什么", "准备东西", "帮我准备", "准备", "推荐", "需要买", "需要带"])

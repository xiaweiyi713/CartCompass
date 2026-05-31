from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TravelContext:
    destination: str
    scenario: str
    query_prefix: str
    is_travel: bool
    is_packing_request: bool


DESTINATION_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("三亚", ("三亚",)),
    ("日本", ("日本", "东京", "大阪", "京都", "北海道", "冲绳")),
    ("韩国", ("韩国", "首尔", "济州")),
    ("泰国", ("泰国", "曼谷", "普吉", "清迈")),
    ("新加坡", ("新加坡",)),
    ("欧洲", ("欧洲", "法国", "巴黎", "意大利", "瑞士", "英国", "德国")),
    ("美国", ("美国", "纽约", "洛杉矶", "夏威夷")),
    ("新疆", ("新疆", "乌鲁木齐", "伊犁", "喀纳斯", "赛里木湖", "独库公路", "阿勒泰", "吐鲁番")),
    ("西藏", ("西藏", "拉萨", "林芝", "日喀则", "阿里")),
    ("云南", ("云南", "大理", "丽江", "香格里拉", "西双版纳")),
    ("川西", ("川西", "稻城", "亚丁", "九寨沟", "四姑娘山")),
    ("青海", ("青海", "西宁", "青海湖", "茶卡盐湖")),
    ("甘肃", ("甘肃", "敦煌", "张掖", "兰州")),
    ("内蒙古", ("内蒙古", "呼伦贝尔", "阿尔山")),
    ("东北", ("东北", "哈尔滨", "漠河", "长白山")),
)

TRAVEL_TERMS = (
    "旅行",
    "旅游",
    "度假",
    "出游",
    "出行",
    "行李",
    "攻略",
    "玩",
    "自驾",
    "露营",
    "徒步",
    "骑行",
    "高原",
    "沙漠",
    "草原",
    "爬山",
    "海边",
    "海岛",
    "温泉",
    "滑雪",
    "城市游",
    "境外",
    "国外",
    "出差",
)

PACKING_TERMS = (
    "要带",
    "带的东西",
    "带什么",
    "买什么",
    "买啥",
    "买哪些",
    "应该买什么",
    "准备",
    "清单",
    "装备",
    "用品",
    "行李",
    "配一套",
)

PRODUCT_SPECIFIC_TERMS = (
    "手机",
    "耳机",
    "电脑",
    "笔记本",
    "平板",
    "充电器",
    "充电宝",
    "防晒",
    "面霜",
    "精华",
    "咖啡",
    "零食",
    "跑鞋",
)


def parse_travel_context(message: str) -> TravelContext:
    compact = _compact(message)
    destination = _destination(compact)
    scenario = _scenario(compact, destination)
    is_travel = bool(destination) or any(term in compact for term in TRAVEL_TERMS)
    packing = any(term in compact for term in PACKING_TERMS)
    product_specific = _is_product_specific(compact)
    generic_recommendation = any(term in compact for term in ("推荐", "买点", "买些", "买什么", "买啥", "买哪些", "应该买什么")) and not product_specific
    travel_product_list_request = bool(destination) and any(term in compact for term in ("玩", "旅游", "旅行", "度假", "出行", "自驾", "露营", "徒步"))
    is_packing_request = is_travel and (not product_specific or travel_product_list_request) and (
        packing or (bool(destination) and generic_recommendation) or travel_product_list_request
    )
    label = destination or "旅行"
    return TravelContext(
        destination=label,
        scenario=scenario,
        query_prefix=f"{label} {scenario} 旅行 便携",
        is_travel=is_travel,
        is_packing_request=is_packing_request,
    )


def _compact(message: str) -> str:
    return re.sub(r"[\s，。！？,.!?]", "", message.lower())


def _destination(compact: str) -> str:
    for label, aliases in DESTINATION_ALIASES:
        if any(alias.lower() in compact for alias in aliases):
            return label
    inferred = _destination_from_travel_phrase(compact)
    if inferred:
        return inferred
    if any(term in compact for term in ("海边", "海岛")):
        return "海边"
    if "温泉" in compact:
        return "温泉"
    if "滑雪" in compact:
        return "滑雪"
    return ""


def _destination_from_travel_phrase(compact: str) -> str:
    patterns = [
        r"(?:想去|我要去|准备去|计划去|打算去|下周去|周末去|去|到)(?P<dest>[\u4e00-\u9fa5a-zA-Z]{2,8}?)(?:玩|旅游|旅行|度假|出差|出行|自驾|徒步|露营|要带|带什么|买什么|买些|买点|应该买)",
        r"(?:推荐|帮我看看|看看)(?P<dest>[\u4e00-\u9fa5a-zA-Z]{2,8}?)(?:旅游|旅行|度假|出行|自驾|徒步|露营)(?:要带|带什么|买什么|用品|装备|清单)?",
    ]
    stop_words = {"手机", "电脑", "笔记本", "平板", "耳机", "东西", "什么", "一下"}
    for pattern in patterns:
        match = re.search(pattern, compact)
        if not match:
            continue
        dest = match.group("dest").strip("的了啊呢吗呀")
        if dest and dest not in stop_words and not any(word in dest for word in stop_words):
            return dest
    return ""


def _scenario(compact: str, destination: str) -> str:
    if any(term in compact for term in ("海边", "海岛", "冲绳", "夏威夷", "三亚")):
        return "海边度假"
    if any(term in compact for term in ("滑雪", "北海道", "雪山")):
        return "寒冷户外"
    if any(term in compact for term in ("新疆", "西藏", "青海", "川西", "甘肃", "敦煌", "吐鲁番", "高原", "沙漠", "自驾")):
        return "高原/干燥户外"
    if any(term in compact for term in ("内蒙古", "呼伦贝尔", "草原", "露营", "徒步", "爬山")):
        return "户外徒步"
    if any(term in compact for term in ("东北", "哈尔滨", "漠河", "长白山")):
        return "寒冷户外"
    if any(term in compact for term in ("云南", "大理", "丽江", "香格里拉")):
        return "高海拔城市观光"
    if any(term in compact for term in ("温泉",)):
        return "温泉度假"
    if any(term in compact for term in ("出差", "商务")):
        return "差旅"
    if "度假" in compact:
        return "度假"
    if destination in {"日本", "韩国", "欧洲", "美国", "新加坡"}:
        return "城市观光"
    return "出行"


def _is_product_specific(compact: str) -> bool:
    return any(term in compact for term in PRODUCT_SPECIFIC_TERMS)

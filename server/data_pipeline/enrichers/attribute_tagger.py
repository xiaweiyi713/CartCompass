from __future__ import annotations


RULES = {
    "skin_type": {
        "油皮": ["油皮", "控油", "清爽", "混油"],
        "干皮": ["干皮", "保湿", "滋润", "补水"],
        "敏感肌": ["敏感肌", "舒缓", "低敏"],
    },
    "features": {
        "控油": ["控油", "清爽"],
        "保湿": ["保湿", "补水", "锁水"],
        "抗初老": ["抗初老", "淡纹", "紧致"],
        "轻量": ["轻量", "轻便", "便携", "lightweight"],
        "通勤": ["通勤", "办公", "商务"],
        "运动": ["跑步", "运动", "缓震"],
        "降噪": ["降噪", "主动降噪"],
        "快充": ["快充", "充电", "fast charge", "fast charging", "high-speed charging", "supercharge", "full-speed", "power delivery"],
        "充电宝": ["充电宝", "power bank", "portable charger", "5000mah", "10000mah", "20000mah", "20k"],
        "充电器": ["充电器", "charger", "charging station", "wall charger", "gan"],
        "数据线": ["数据线", "cable", "usb-c to usb-c"],
        "多设备": ["多设备", "multi-device", "simultaneously", "charge 2 devices", "three devices", "two-port", "3 ports", "6-in-1"],
        "笔记本适用": ["笔记本", "laptop", "macbook"],
    },
    "scenario": {
        "夏季": ["夏季", "防晒", "清爽"],
        "日常": ["日常", "通勤", "办公"],
        "旅行": ["旅行", "出差", "便携", "收纳", "travel", "portable", "compact", "nano"],
        "办公": ["办公", "laptop", "macbook", "desk", "charging station"],
        "户外": ["户外", "防水", "防晒"],
    },
    "exclude_ingredients": {
        "酒精": ["不含酒精", "无酒精", "0酒精"],
        "皂基": ["不含皂基", "无皂基", "氨基酸"],
        "香精": ["不含香精", "无香精"],
    },
}


def enrich_attributes(title: str, description: str) -> dict[str, list[str]]:
    text = f"{title} {description}".lower()
    enriched: dict[str, list[str]] = {}
    for field, rules in RULES.items():
        values = [label for label, keywords in rules.items() if any(keyword in text for keyword in keywords)]
        enriched[field] = values
    tags = sorted({value for values in enriched.values() for value in values})
    enriched["tags"] = tags
    return enriched


def build_review_summary(description: str) -> dict[str, list[str]]:
    positives: list[str] = []
    negatives: list[str] = []
    for word in ("清爽", "温和", "保湿", "轻便", "降噪", "快充", "通勤", "缓震"):
        if word in description:
            positives.append(word)
    for word in ("紧绷", "偏重", "偏贵", "香味", "续航一般"):
        if word in description:
            negatives.append(word)
    return {
        "positive": positives[:4],
        "negative": negatives[:4],
    }

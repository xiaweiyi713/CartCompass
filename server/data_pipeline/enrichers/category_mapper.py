from __future__ import annotations


CATEGORY_ALIASES = {
    "护肤": ("美妆护肤", "护肤"),
    "美妆": ("美妆护肤", "护肤"),
    "洁面": ("美妆护肤", "洁面"),
    "防晒": ("美妆护肤", "防晒"),
    "面霜": ("美妆护肤", "面霜"),
    "精华": ("美妆护肤", "精华"),
    "耳机": ("数码电子", "耳机"),
    "手机": ("数码电子", "智能手机"),
    "充电器": ("数码电子", "充电器"),
    "数码": ("数码电子", "数码配件"),
    "跑鞋": ("服饰运动", "运动鞋"),
    "双肩包": ("服饰运动", "箱包"),
    "防晒衣": ("服饰运动", "外套"),
    "服饰": ("服饰运动", "服饰"),
    "收纳": ("食品生活", "旅行收纳"),
    "墨镜": ("服饰运动", "配饰"),
    "凉鞋": ("服饰运动", "鞋靴"),
}


def map_category(category_hint: str, sub_category_hint: str, text: str) -> tuple[str, str]:
    joined = f"{category_hint} {sub_category_hint} {text}"
    for keyword, mapped in CATEGORY_ALIASES.items():
        if keyword in joined:
            category, sub_category = mapped
            return category_hint or category, sub_category_hint or sub_category
    return category_hint or "食品生活", sub_category_hint or "综合商品"

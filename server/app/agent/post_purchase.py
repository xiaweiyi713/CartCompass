from __future__ import annotations

from app.models.schemas import OrderState, Product
from app.rag.product_repository import ProductRepository, SearchConstraints


class PostPurchaseRecommender:
    def __init__(self, products: ProductRepository) -> None:
        self.products = products

    def recommendations_for_order(self, order: OrderState, limit: int = 4) -> list[Product]:
        picked: list[Product] = []
        seen = {item.product_id for item in order.items}
        for item in order.items:
            product = self.products.get(item.product_id)
            if not product:
                continue
            for candidate in self._candidates(product):
                if candidate.product_id in seen:
                    continue
                seen.add(candidate.product_id)
                picked.append(candidate)
                if len(picked) >= limit:
                    return picked
        return picked

    def _candidates(self, product: Product) -> list[Product]:
        if product.category == "数码电子":
            if "手机" in product.sub_category or "手机" in product.title:
                return self._search("手机 快充 充电器 充电宝 耳机 保护 配件", "数码电子", None)
            if "充电" in product.sub_category or "充电" in product.title:
                return self._search("数据线 充电宝 多设备 配件", "数码电子", None)
            return self._search("数码 配件 快充 便携", "数码电子", None)
        if product.category == "美妆护肤":
            if "防晒" in product.sub_category or "防晒" in product.title:
                return self._search("卸妆 洁面 保湿 修护 敏感肌", "美妆护肤", None)
            return self._search("防晒 保湿 修护 洁面", "美妆护肤", None)
        if product.category == "食品饮料":
            return self._search("低糖 无糖 咖啡 坚果 补充购买", "食品饮料", None)
        if product.category == "服饰运动":
            return self._search("户外 速干 防晒 背包 鞋 运动", "服饰运动", None)
        return []

    def _search(self, query: str, category: str, sub_category: str | None) -> list[Product]:
        constraints = SearchConstraints(category=category, sub_category=sub_category)
        results = self.products.search(query, constraints, limit=6)
        for product in results:
            product.reason = f"订单后补充推荐：{product.reason or product.sub_category}"
            product.match_reasons.insert(0, "订单后推荐：按已购商品类目寻找配件、补充购买或复购候选")
        return results

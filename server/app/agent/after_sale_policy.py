from __future__ import annotations

from app.models.schemas import Product


class AfterSalePolicyService:
    """Grounded, deterministic after-sale policy explainer.

    The project does not integrate a real marketplace order system, so this
    service deliberately avoids promising platform-specific refund windows.
    It explains demo policy boundaries and points users to source/order facts.
    """

    def answer(self, product: Product | None, question: str = "") -> str:
        if not product:
            return (
                "当前没有指定商品，我只能给通用说明：本项目是导购 Demo，不模拟真实支付、物流和平台售后。"
                "购物车里的“模拟下单”只生成本地订单号；真实退换货需以商品来源平台和商家页面为准。"
            )

        parts = [
            f"关于 {product.title[:28]} 的售后/退换货，我只能基于本地商品库和 Demo 规则回答：",
            "本项目不承诺真实平台退换货窗口、库存、运费险或保修期限；模拟下单不会产生真实支付和物流。",
        ]
        if product.source_url:
            parts.append(f"这款商品记录了公开来源 {product.source_name}，真实退换货政策应以来源页面和下单平台规则为准。")
        else:
            parts.append("这款商品缺少公开来源链接，售后政策证据不足，建议只把它作为演示候选。")

        if product.category == "美妆护肤":
            parts.append("护肤/美妆类商品通常需要重点核对是否未拆封、是否影响二次销售，以及过敏等特殊情况的举证要求。")
        elif product.category == "数码电子":
            parts.append("数码类商品建议重点核对激活状态、序列号、保修主体、配件完整度和人为损坏排除条款。")
        elif product.category == "食品饮料":
            parts.append("食品饮料类商品通常需要重点核对保质期、破损漏液、临期和非质量问题退换限制。")
        elif product.category == "服饰运动":
            parts.append("服饰运动类商品建议重点核对吊牌、洗涤痕迹、尺码换货和影响二次销售的限制。")

        parts.append("建议下单前在详情页查看来源、评论风险和 SKU 信息；如用于答辩，可说明系统不会编造未落库售后承诺。")
        return "".join(parts)

    def payload(self, product: Product | None) -> dict:
        return {
            "product_id": product.product_id if product else None,
            "source_name": product.source_name if product else None,
            "source_url": product.source_url if product else None,
            "disclaimer": "本项目为导购 Demo，不产生真实支付、物流或平台售后承诺。",
        }

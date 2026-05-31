from __future__ import annotations

from app.models.schemas import FallbackNotice, RecoveryAction
from app.rag.product_repository import SearchConstraints


def notice(kind: str, message: str | None = None, actions: list[RecoveryAction] | None = None) -> FallbackNotice:
    defaults = {
        "model_unavailable": FallbackNotice(
            code="model_unavailable",
            title="模型连接暂时不可用",
            message="我已自动切换到本地商品检索和规则兜底，你可以继续使用导购功能。",
            actions=[
                RecoveryAction(label="检查模型配置", prompt="打开模型大脑设置"),
                RecoveryAction(label="继续本地导购", prompt="推荐手机"),
            ],
            severity="warning",
        ),
        "model_config_failed": FallbackNotice(
            code="model_config_failed",
            title="模型配置没有通过测试",
            message="当前 API Key、模型名或端点不可用，暂时不会切换 Agent 大脑。你仍然可以继续使用本地检索、RAG 和规则导购。",
            actions=[
                RecoveryAction(label="检查 Key/端点", prompt="打开模型大脑设置"),
                RecoveryAction(label="继续本地导购", prompt="推荐手机"),
            ],
            severity="warning",
        ),
        "structured_output_failed": FallbackNotice(
            code="structured_output_failed",
            title="模型结构化输出未通过校验",
            message="模型输出没有满足工具调用格式，我已丢弃不可靠输出并回退到确定性解析和本地检索。",
            actions=[
                RecoveryAction(label="继续本地导购", prompt="推荐手机"),
                RecoveryAction(label="换个说法重试", prompt="用预算、类目和排除条件重新描述需求"),
            ],
            severity="warning",
        ),
        "chat_exception": FallbackNotice(
            code="chat_exception",
            title="这次回复没有顺利完成",
            message="对话服务遇到异常，但购物车和商品库仍可用。你可以换个说法重试，或先从常用推荐继续。",
            actions=[
                RecoveryAction(label="重新说需求", prompt="推荐适合我的商品"),
                RecoveryAction(label="看旅行方案", prompt="我要去成都旅行，应该买什么"),
            ],
            severity="error",
        ),
        "empty_recommendation": FallbackNotice(
            code="empty_recommendation",
            title="没有完全符合条件的商品",
            message=message or "当前商品库没有找到完全满足所有条件的结果，可以放宽一个约束继续找。",
            actions=actions or [
                RecoveryAction(label="放宽预算", prompt="预算可以稍微放宽一点"),
                RecoveryAction(label="保留核心条件", prompt="保留核心条件，给我相近替代品"),
                RecoveryAction(label="换个品牌", prompt="换个品牌看看"),
            ],
            severity="info",
        ),
        "image_empty": FallbackNotice(
            code="image_empty",
            title="没有找到足够相似的图片商品",
            message="我没有把这张图强行匹配到不可靠商品。你可以加一句文字需求，或换一张更清晰的商品主体图。",
            actions=[
                RecoveryAction(label="加文字需求", prompt="按这张图找同类商品，预算300以内"),
                RecoveryAction(label="改用文字推荐", prompt="描述一下商品类型和预算"),
            ],
            severity="info",
        ),
        "image_failed": FallbackNotice(
            code="image_failed",
            title="图片识别暂时失败",
            message="图片可能无法解析或网络暂时异常。文字导购仍可继续使用，也可以重新上传一张清晰图片。",
            actions=[
                RecoveryAction(label="重新上传图片", prompt="重新上传图片"),
                RecoveryAction(label="改用文字描述", prompt="我想找和图片类似的商品"),
            ],
            severity="warning",
        ),
        "empty_cart_checkout": FallbackNotice(
            code="empty_cart_checkout",
            title="购物车还是空的",
            message="还没有可结算的商品。先让 Agent 推荐商品，加入购物车后再进入沙箱结算。",
            actions=[
                RecoveryAction(label="推荐旅行用品", prompt="我要去三亚度假，应该买些什么"),
                RecoveryAction(label="推荐手机", prompt="推荐手机"),
            ],
            severity="info",
        ),
        "payment_failed": FallbackNotice(
            code="payment_failed",
            title="沙箱支付未完成",
            message="这次是演示支付失败，购物车和结算会话仍保留。你可以返回结算台重试成功、取消或超时场景。",
            actions=[
                RecoveryAction(label="返回结算台", prompt="返回结算台重试支付"),
                RecoveryAction(label="检查购物车", prompt="查看购物车"),
            ],
            severity="warning",
        ),
        "network_failed": FallbackNotice(
            code="network_failed",
            title="网络连接失败",
            message="暂时无法连接本机后端。请确认后端服务运行在 127.0.0.1:8000，稍后可以直接重试。",
            actions=[
                RecoveryAction(label="重试刚才的问题", prompt="重试刚才的问题"),
                RecoveryAction(label="先看本地建议", prompt="推荐手机"),
            ],
            severity="error",
        ),
    }
    base = defaults[kind]
    if message is None and actions is None:
        return base
    return FallbackNotice(
        code=base.code,
        title=base.title,
        message=message or base.message,
        actions=actions or base.actions,
        severity=base.severity,
    )


def empty_recommendation_notice(message: str, constraints: SearchConstraints) -> FallbackNotice:
    actions: list[RecoveryAction] = []
    if constraints.max_price:
        wider = int(max(constraints.max_price + 50, constraints.max_price * 1.5))
        actions.append(RecoveryAction(label=f"放宽预算到 {wider} 元", prompt=f"预算放宽到{wider}元，其他条件不变"))
    if constraints.exclude_brands:
        actions.append(RecoveryAction(label="放宽品牌限制", prompt="保留核心需求，先不限制品牌"))
    if constraints.exclude_terms:
        actions.append(RecoveryAction(label="保留排除条件找替代", prompt="保留排除条件，给我相近替代品"))
    if not actions:
        actions = [
            RecoveryAction(label="放宽预算", prompt="预算可以稍微放宽一点"),
            RecoveryAction(label="换个类目", prompt="换一个相近类目看看"),
            RecoveryAction(label="查看相近替代品", prompt="给我相近替代品"),
        ]
    return notice("empty_recommendation", message=message, actions=actions[:3])

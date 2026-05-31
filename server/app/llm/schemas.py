from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


IntentName = Literal[
    "smalltalk",
    "recommend_product",
    "compare_products",
    "cart_action",
    "checkout",
    "product_qa",
    "travel_bundle",
    "image_search",
    "profile_action",
    "unknown",
]


class IntentInput(BaseModel):
    user_message: str
    recent_context: list[str] = Field(default_factory=list)
    current_topic: str | None = None


class IntentOutput(BaseModel):
    intent: IntentName
    confidence: float = Field(ge=0, le=1)
    topic_shift: bool = False
    need_clarification: bool = False


class ConstraintInput(BaseModel):
    user_message: str
    current_constraints: dict = Field(default_factory=dict)


class ConstraintOutput(BaseModel):
    category: str | None = None
    sub_category: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    include_preferences: list[str] = Field(default_factory=list)
    exclude_brands: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    sort_preference: str | None = None


class GroundedProductFact(BaseModel):
    product_id: str
    name: str
    brand: str
    category: str
    sub_category: str
    price: float
    source_name: str
    evidence: list[str] = Field(default_factory=list)
    match_reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class GroundedAnswerPacket(BaseModel):
    task: Literal["recommendation", "comparison", "product_qa", "checkout_review"] = "recommendation"
    user_query: str
    constraints: dict = Field(default_factory=dict)
    selected_products: list[GroundedProductFact] = Field(default_factory=list)
    forbidden: list[str] = Field(
        default_factory=lambda: [
            "不要新增商品、价格、库存、优惠、销量或官方承诺",
            "不要生成商品卡片字段",
            "不要提及不在 evidence、match_reasons 或商品字段中的参数",
        ]
    )
    style: str = "自然中文，简洁，最多推荐 3 款"


class ReviewSummaryInput(BaseModel):
    product_id: str
    reviews: list[dict] = Field(default_factory=list)


class ReviewSummaryOutput(BaseModel):
    positive_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    summary: str
    risk_flags: list[str] = Field(default_factory=list)


class ModelCapability(BaseModel):
    supports_stream: bool = True
    supports_json_mode: bool | str = False
    supports_tool_call: bool | str = False
    best_for: list[str] = Field(default_factory=list)
    not_recommended_for: list[str] = Field(default_factory=list)
    max_context: int | None = None


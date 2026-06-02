from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class ConversationPlanInput(BaseModel):
    user_message: str
    history: list[dict] = Field(default_factory=list)
    has_last_products: bool = False
    has_active_category: bool = False
    cart_item_count: int = 0


class ConversationPlan(BaseModel):
    """The LLM planner's decision for one turn: what the user wants, how strong
    the shopping intent is, and (for conversational turns) a natural reply.

    Product facts are never produced here — shopping intents are dispatched to
    deterministic tools that read the catalog, so grounding is preserved."""

    intent: Literal[
        "smalltalk",
        "product_knowledge",
        "weather",
        "recommend",
        "compare",
        "cart",
        "product_qa",
        "after_sale",
        "budget_plan",
        "travel_bundle",
        "feedback",
        "clarify",
        "unknown",
    ] = "unknown"
    # 0 = pure chat, 1-2 = vague interest (offer help, no cards), 3 = explicit
    # recommendation, 4 = transaction (cart / checkout).
    shopping_intent_level: int = 0
    # Natural-language reply for conversational intents only (smalltalk /
    # product_knowledge / weather / clarify). Empty for catalog-backed intents,
    # whose text comes from the grounded answer pipeline.
    reply: str = ""
    rationale: str = ""


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

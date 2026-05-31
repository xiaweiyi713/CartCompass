from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SKU(BaseModel):
    sku_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    price: float
    image_url: str | None = None
    image_source_url: str | None = None


class Product(BaseModel):
    product_id: str
    title: str
    brand: str
    category: str
    sub_category: str
    base_price: float
    image_url: str
    skus: list[SKU] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    reason: str = ""
    source_url: str | None = None
    source_name: str = "赛题示例商品库"
    evidence: list[str] = Field(default_factory=list)
    average_rating: float | None = None
    review_count: int = 0
    match_score: int = 0
    match_reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    user_id: str
    budget_preferences: dict[str, float] = Field(default_factory=dict)
    preferred_features: list[str] = Field(default_factory=list)
    excluded_brands: list[str] = Field(default_factory=list)
    excluded_ingredients: list[str] = Field(default_factory=list)
    skin_type: str | None = None
    travel_scenario: list[str] = Field(default_factory=list)
    last_feedback: list[dict[str, str]] = Field(default_factory=list)


class ShoppingPlanItem(BaseModel):
    role: str
    product: Product
    reason: str
    optional: bool = False


class ShoppingPlan(BaseModel):
    title: str
    budget: float
    total_price: float
    remaining_budget: float
    items: list[ShoppingPlanItem]
    upgrade_options: list[ShoppingPlanItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WeatherLocation(BaseModel):
    name: str
    country: str | None = None
    latitude: float
    longitude: float
    timezone: str | None = None


class CurrentWeather(BaseModel):
    temperature_c: float | None = None
    apparent_temperature_c: float | None = None
    condition: str = "天气状况未知"
    precipitation_mm: float | None = None
    rain_probability: float | None = None
    humidity: float | None = None
    wind_speed_kmh: float | None = None
    uv_index: float | None = None
    is_day: bool | None = None


class DailyWeather(BaseModel):
    date: str
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    precipitation_probability_max: float | None = None
    uv_index_max: float | None = None
    condition: str | None = None


class WeatherImplications(BaseModel):
    tags: list[str] = Field(default_factory=list)
    shopping_needs: list[str] = Field(default_factory=list)
    travel_advice: list[str] = Field(default_factory=list)


class WeatherContext(BaseModel):
    location: WeatherLocation
    current: CurrentWeather | None = None
    daily: list[DailyWeather] = Field(default_factory=list)
    implications: WeatherImplications = Field(default_factory=WeatherImplications)
    source: str
    fetched_at: str


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str


class LLMConfigRequest(BaseModel):
    session_id: str = "default"
    provider: Literal["ark", "deepseek", "openai_compatible", "anthropic", "disabled"] = "deepseek"
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.2
    temporary: bool = True


class LLMTestRequest(BaseModel):
    session_id: str = "default"
    provider: Literal["ark", "deepseek", "openai_compatible", "anthropic", "disabled"] | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0


class LLMStatus(BaseModel):
    configured: bool
    provider: str
    model: str | None = None
    base_url: str | None = None
    source: str = "fallback"
    key_present: bool = False
    key_hint: str | None = None


class RecoveryAction(BaseModel):
    label: str
    prompt: str


class FallbackNotice(BaseModel):
    code: str = "general"
    title: str
    message: str
    actions: list[RecoveryAction] = Field(default_factory=list)
    severity: Literal["info", "warning", "error"] = "info"


class CartItem(BaseModel):
    line_id: str
    product: Product
    quantity: int = 1
    selected_sku: SKU | None = None
    unit_price: float


class CartState(BaseModel):
    session_id: str
    items: list[CartItem] = Field(default_factory=list)
    total_price: float = 0


class AddCartRequest(BaseModel):
    session_id: str = "default"
    product_id: str
    quantity: int = 1
    sku_id: str | None = None


class UpdateCartRequest(BaseModel):
    session_id: str = "default"
    product_id: str
    quantity: int
    sku_id: str | None = None


class CheckoutRequest(BaseModel):
    session_id: str = "default"
    address: str = "默认地址"


class CheckoutSessionRequest(BaseModel):
    session_id: str = "default"
    user_id: str | None = None
    address: str = "默认地址"
    payment_mode: Literal["mock"] = "mock"
    success_url: str | None = None
    cancel_url: str | None = None


class CheckoutSessionResponse(BaseModel):
    checkout_session_id: str
    checkout_url: str
    expires_at: str
    status: str
    total_amount: float
    currency: str = "CNY"
    review: list[str] = Field(default_factory=list)


class MockPaymentRequest(BaseModel):
    outcome: Literal["success", "failed", "cancelled", "timeout"] = "success"


class OrderItem(BaseModel):
    product_id: str
    title: str
    unit_price: float
    quantity: int
    subtotal: float
    sku_id: str | None = None
    sku_text: str | None = None


class OrderState(BaseModel):
    order_id: str
    session_id: str
    address: str
    items: list[OrderItem]
    total_price: float
    status: str = "created"
    payment_status: str = "UNPAID"
    payment_provider: str = "mock"
    checkout_session_id: str | None = None
    paid_at: str | None = None
    post_purchase_recommendations: list[Product] = Field(default_factory=list)


class SSEEvent(BaseModel):
    event: Literal["token", "products", "compare", "cart", "plan", "travel_plan", "profile", "fallback", "error", "done"]
    data: Any

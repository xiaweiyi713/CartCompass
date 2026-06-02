from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from app.agent.after_sale_policy import AfterSalePolicyService
from app.agent.cart import CartService
from app.agent.orchestrator import AgentOrchestrator
from app.agent.session_store import SessionStore
from app.agent.user_profile import UserProfileService
from app.checkout.session_service import CheckoutService
from app.models.schemas import (
    AddCartRequest,
    ChatRequest,
    CheckoutRequest,
    CheckoutSessionRequest,
    LLMConfigRequest,
    LLMTestRequest,
    MockPaymentRequest,
    UpdateCartRequest,
)
from app.observability import observability
from app.rag.image_search import ImageSearchService
from app.rag.product_repository import ProductRepository, SearchConstraints
from app.recovery import notice


router = APIRouter(prefix="/api")
admin_router = APIRouter()
products = ProductRepository()
cart = CartService(products)
checkout_service = CheckoutService(cart)
sessions = SessionStore()
profiles = UserProfileService()
agent = AgentOrchestrator(products, cart, sessions, profiles)
image_search_service = ImageSearchService(products)
after_sale_policy = AfterSalePolicyService()


@router.get("/health")
def health() -> dict:
    embedding_client = products.semantic_store.client
    return {
        "ok": True,
        "product_count": len(products.all()),
        "llm_configured": agent.llm.is_configured,
        "llm": agent.llm.status().model_dump(),
        "text_embedding": {
            "configured": products.semantic_store.is_configured,
            "provider": products.semantic_store.identity[0],
            "model": products.semantic_store.identity[1],
            "base_url": embedding_client.config.base_url,
            "disabled_reason": embedding_client.disabled_reason,
        },
    }


@router.get("/llm/status")
def llm_status(session_id: str = "default") -> dict:
    return agent.llm.status(session_id).model_dump()


@router.post("/llm/config")
def configure_llm(request: LLMConfigRequest) -> dict:
    try:
        return agent.llm.configure(request).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/llm/config/{session_id}")
def clear_llm_config(session_id: str) -> dict:
    return agent.llm.clear(session_id).model_dump()


@router.post("/llm/test")
async def test_llm(request: LLMTestRequest) -> dict:
    try:
        result = await agent.llm.test_connection(request)
        if not result.get("ok"):
            result["fallback"] = notice("model_config_failed", message=result.get("message")).model_dump()
        return result
    except ValueError as exc:
        fallback = notice("model_config_failed", message=str(exc)).model_dump()
        return JSONResponse(status_code=400, content={"detail": str(exc), "fallback": fallback})


@router.get("/metrics")
def metrics() -> dict:
    return observability.snapshot(_product_stats())


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str) -> dict:
    trace = observability.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.get("/profile/{session_id}")
def get_profile(session_id: str) -> dict:
    return profiles.get(session_id).model_dump()


@router.delete("/profile/{session_id}")
def clear_profile(session_id: str) -> dict:
    observability.increment("profile_clears")
    return profiles.clear(session_id).model_dump()


@admin_router.get("/admin/metrics", response_class=HTMLResponse)
def admin_metrics() -> HTMLResponse:
    return HTMLResponse(observability.render_html(_product_stats()))


@router.get("/products")
def list_products(
    query: str = "",
    category: str | None = None,
    max_price: float | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict]:
    if query or category or max_price is not None:
        constraints = SearchConstraints(category=category, max_price=max_price)
        return [product.model_dump() for product in products.search(query, constraints, limit=limit)]
    return [product.model_dump() for product in products.all()]


@router.get("/weather/current")
async def current_weather(location: str, days: int = Query(default=7, ge=1, le=7)) -> dict:
    context = await agent.weather.lookup(location, days=days)
    if not context:
        raise HTTPException(status_code=404, detail=f"Weather not available for {location}")
    return context.model_dump()


@router.get("/products/{product_id}")
def get_product(product_id: str) -> dict:
    product = products.get(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product.model_dump()


@router.get("/products/{product_id}/alternatives")
def product_alternatives(
    product_id: str,
    mode: str = Query(default="cheaper", pattern="^(cheaper|premium|brand_excluded)$"),
    query: str = "",
    excluded_brand: list[str] = Query(default=[]),
    limit: int = Query(default=3, ge=1, le=10),
) -> dict:
    if not products.get(product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    alternatives = products.alternatives(product_id, mode=mode, query=query, excluded_brands=excluded_brand, limit=limit)
    return {"products": [product.model_dump() for product in alternatives]}


@router.get("/products/{product_id}/after_sale")
def product_after_sale(product_id: str, question: str = "") -> dict:
    product = products.get(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
        "answer": after_sale_policy.answer(product, question),
        "policy": after_sale_policy.payload(product),
    }


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        agent.chat_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/cart/add")
def add_cart(request: AddCartRequest) -> dict:
    if not products.get(request.product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        state = cart.add(request.session_id, request.product_id, request.quantity, request.sku_id)
        observability.increment("cart_operation_success")
        return state.model_dump()
    except ValueError as exc:
        observability.increment("cart_operation_failure")
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cart/update")
def update_cart(request: UpdateCartRequest) -> dict:
    if not products.get(request.product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        state = cart.update(request.session_id, request.product_id, request.quantity, request.sku_id)
        observability.increment("cart_operation_success")
        return state.model_dump()
    except ValueError as exc:
        observability.increment("cart_operation_failure")
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/cart/{session_id}/{product_id}")
def remove_cart(session_id: str, product_id: str, sku_id: str | None = None) -> dict:
    state = cart.remove(session_id, product_id, sku_id)
    observability.increment("cart_operation_success")
    return state.model_dump()


@router.delete("/cart/{session_id}")
def clear_cart(session_id: str) -> dict:
    state = cart.clear(session_id)
    observability.increment("cart_operation_success")
    return state.model_dump()


@router.get("/cart/{session_id}")
def get_cart(session_id: str) -> dict:
    return cart.state(session_id).model_dump()


@router.post("/cart/checkout")
def checkout(request: CheckoutRequest) -> dict:
    try:
        order = cart.checkout(request.session_id, request.address)
        observability.increment("checkout_success")
        return order.model_dump()
    except ValueError as exc:
        observability.increment("checkout_failure")
        fallback = notice("empty_cart_checkout", message=str(exc)).model_dump()
        return JSONResponse(status_code=400, content={"detail": str(exc), "fallback": fallback})


@router.post("/checkout/session")
def create_checkout_session(request: CheckoutSessionRequest, http_request: Request) -> dict:
    try:
        base_url = str(http_request.base_url).rstrip("/")
        session = checkout_service.create_session(
            session_id=request.session_id,
            user_id=request.user_id,
            address=request.address,
            payment_mode=request.payment_mode,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
            base_url=base_url,
        )
        return {
            "checkout_session_id": session.checkout_session_id,
            "checkout_url": session.checkout_url,
            "expires_at": session.expires_at.isoformat(),
            "status": session.status,
            "total_amount": session.cart_snapshot.total_price,
            "currency": session.currency,
            "review": session.review,
        }
    except ValueError as exc:
        observability.increment("checkout_session_failure")
        fallback = notice("empty_cart_checkout", message=str(exc)).model_dump()
        return JSONResponse(status_code=400, content={"detail": str(exc), "fallback": fallback})


@router.get("/checkout/session/{checkout_session_id}")
def get_checkout_session(checkout_session_id: str) -> dict:
    session = checkout_service.get_session(checkout_session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Checkout session not found")
    return {
        "checkout_session_id": session.checkout_session_id,
        "status": session.status,
        "order_id": session.order_id,
        "total_amount": session.cart_snapshot.total_price,
        "currency": session.currency,
        "expires_at": session.expires_at.isoformat(),
        "review": session.review,
    }


@router.post("/checkout/{checkout_session_id}/pay/mock")
def pay_checkout_mock(
    checkout_session_id: str,
    http_request: Request,
    payload: MockPaymentRequest | None = None,
    outcome: str | None = Query(default=None, pattern="^(success|failed|cancelled|timeout)$"),
):
    requested_outcome = outcome or (payload.outcome if payload else "success")
    try:
        result = checkout_service.pay_mock(checkout_session_id, requested_outcome)
    except ValueError as exc:
        observability.increment("mock_payment_failure")
        fallback = notice("payment_failed", message=str(exc)).model_dump()
        return JSONResponse(status_code=400, content={"detail": str(exc), "fallback": fallback})
    accept = http_request.headers.get("accept", "")
    if "text/html" in accept:
        return RedirectResponse(f"/checkout/success?session_id={checkout_session_id}", status_code=303)
    if hasattr(result, "model_dump"):
        payload = result.model_dump()
        if getattr(result, "status", "") in {"FAILED", "CANCELLED"}:
            payload["fallback"] = notice("payment_failed", message=getattr(result, "failure_reason", None)).model_dump()
        return payload
    return {
        "checkout_session_id": result.checkout_session_id,
        "status": result.status,
        "failure_reason": result.failure_reason,
        "fallback": notice("payment_failed", message=result.failure_reason).model_dump(),
    }


@router.get("/orders/{order_id}")
def get_order(order_id: str) -> dict:
    order = checkout_service.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order.model_dump()


@router.post("/image_search")
async def image_search(file: UploadFile = File(...), query: str = "") -> dict:
    content = await file.read()
    trace_id = observability.start_trace("image_search", {"filename": file.filename, "query": query})
    trace_token = observability.set_current_trace(trace_id)
    try:
        results = await image_search_service.search_async(content, query=query, limit=5)
        observability.finish_trace(trace_id, "ok")
        payload = {"trace_id": trace_id, "products": [product.model_dump() for product in results]}
        if not results:
            payload["fallback"] = notice("image_empty").model_dump()
        return payload
    except Exception:
        observability.finish_trace(trace_id, "error")
        return {
            "trace_id": trace_id,
            "products": [],
            "fallback": notice("image_failed").model_dump(),
        }
    finally:
        observability.reset_current_trace(trace_token)


def _product_stats() -> dict[str, str | int]:
    all_products = products.all()
    total = len(all_products)
    source_count = sum(1 for product in all_products if product.source_url)
    review_count = sum(1 for product in all_products if product.review_count > 0)
    sku_count = sum(1 for product in all_products if product.skus)
    sku_image_count = sum(1 for product in all_products if any(sku.image_url for sku in product.skus))
    public_image_count = sum(1 for product in all_products if product.image_url)
    total_reviews = sum(product.review_count for product in all_products)
    return {
        "商品总数": total,
        "公开来源商品占比": _ratio(source_count, total),
        "有评论商品占比": _ratio(review_count, total),
        "有 SKU 商品占比": _ratio(sku_count, total),
        "有规格图商品占比": _ratio(sku_image_count, total),
        "有主图商品占比": _ratio(public_image_count, total),
        "评论总量": total_reviews,
    }


def _ratio(count: int, total: int) -> str:
    if total == 0:
        return "0/0 (0.0%)"
    return f"{count}/{total} ({count / total * 100:.1f}%)"


@admin_router.get("/checkout/success", response_class=HTMLResponse)
def checkout_success(session_id: str) -> Response:
    return _utf8_html(checkout_service.render_result_html(session_id))


@admin_router.get("/checkout/{checkout_session_id}", response_class=HTMLResponse)
def checkout_page(checkout_session_id: str) -> Response:
    return _utf8_html(checkout_service.render_checkout_html(checkout_session_id))


def _utf8_html(html: str) -> Response:
    return Response(
        content=html.encode("utf-8"),
        media_type="text/html",
        headers={"Content-Type": "text/html; charset=utf-8"},
    )

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape
from textwrap import dedent
from uuid import uuid4

from app.agent.cart import CartService
from app.models.schemas import CartItem, CartState, OrderItem, OrderState
from app.observability import observability


@dataclass
class CheckoutSession:
    checkout_session_id: str
    user_id: str
    cart_snapshot: CartState
    address: str
    payment_mode: str
    checkout_url: str
    success_url: str | None
    cancel_url: str | None
    status: str
    currency: str
    review: list[str]
    created_at: datetime
    expires_at: datetime
    order_id: str | None = None
    failure_reason: str | None = None


@dataclass
class CheckoutService:
    cart: CartService
    sessions: dict[str, CheckoutSession] = field(default_factory=dict)
    orders: dict[str, OrderState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._lock = threading.RLock()

    def create_session(
        self,
        session_id: str,
        user_id: str | None,
        address: str,
        payment_mode: str = "mock",
        success_url: str | None = None,
        cancel_url: str | None = None,
        base_url: str = "http://127.0.0.1:8000",
    ) -> CheckoutSession:
        with self._lock:
            cart_state = self.cart.state(session_id)
            if not cart_state.items:
                raise ValueError("购物车为空，无法创建结算会话")
            checkout_session_id = f"cs_demo_{uuid4().hex[:12]}"
            now = datetime.now(timezone.utc)
            session = CheckoutSession(
                checkout_session_id=checkout_session_id,
                user_id=user_id or session_id,
                cart_snapshot=cart_state,
                address=address,
                payment_mode=payment_mode,
                checkout_url=f"{base_url.rstrip('/')}/checkout/{checkout_session_id}",
                success_url=success_url,
                cancel_url=cancel_url,
                status="CREATED",
                currency="CNY",
                review=self._review(cart_state),
                created_at=now,
                expires_at=now + timedelta(minutes=30),
            )
            self.sessions[checkout_session_id] = session
        observability.increment("checkout_session_created")
        observability.add_current_step(
            "checkout_session",
            {
                "checkout_session_id": checkout_session_id,
                "cart_session_id": session_id,
                "items": len(cart_state.items),
                "total_amount": cart_state.total_price,
                "payment_mode": payment_mode,
            },
        )
        return session

    def get_session(self, checkout_session_id: str) -> CheckoutSession | None:
        with self._lock:
            return self.sessions.get(checkout_session_id)

    def get_order(self, order_id: str) -> OrderState | None:
        with self._lock:
            return self.orders.get(order_id)

    def pay_mock(self, checkout_session_id: str, outcome: str) -> OrderState | CheckoutSession:
        with self._lock:
            session = self._active_session_or_raise(checkout_session_id)
            if outcome != "success":
                session.status = "CANCELLED" if outcome == "cancelled" else "FAILED"
                session.failure_reason = {
                    "failed": "余额不足或卡片被拒绝",
                    "cancelled": "用户取消了沙箱支付",
                    "timeout": "沙箱支付超时",
                }.get(outcome, "沙箱支付失败")
                observability.increment(f"mock_payment_{outcome}")
                return session

            order = self._build_order(session)
            session.status = "PAID"
            session.order_id = order.order_id
            self.orders[order.order_id] = order
            self.cart.clear(session.cart_snapshot.session_id)
        observability.increment("mock_payment_success")
        observability.increment("checkout_paid_test")
        return order

    def render_checkout_html(self, checkout_session_id: str) -> str:
        session = self.get_session(checkout_session_id)
        if not session:
            return self._page_shell("结算会话不存在", "<main><h1>结算会话不存在</h1><p>请回到 App 重新创建结算。</p></main>")
        rows = "".join(self._item_row(item) for item in session.cart_snapshot.items)
        review = "".join(f"<li>{escape(item)}</li>" for item in session.review)
        disabled = "disabled" if session.status != "CREATED" else ""
        status = escape(session.status)
        body = f"""
        <main class="layout">
          <section class="hero">
            <div>
              <p class="eyebrow">ShopGuide Virtual Mall</p>
              <h1>沙箱结算台</h1>
              <p class="notice">这是演示环境，不会产生真实扣款，也不会收集银行卡信息。</p>
            </div>
            <div class="status">状态 <strong>{status}</strong></div>
          </section>
          <section class="grid">
            <div class="panel order">
              <h2>订单商品</h2>
              <div class="items">{rows}</div>
            </div>
            <aside class="panel summary">
              <h2>Agent 审查</h2>
              <ul>{review}</ul>
              <div class="address">
                <span>收货信息</span>
                <strong>{escape(session.address)}</strong>
              </div>
              <div class="total">
                <span>应付金额</span>
                <strong>¥{session.cart_snapshot.total_price:.0f}</strong>
              </div>
              <form method="post" action="/api/checkout/{escape(checkout_session_id)}/pay/mock?outcome=success">
                <button {disabled} class="pay" type="submit">Mock Pay 支付成功</button>
              </form>
              <div class="fail-actions">
                <form method="post" action="/api/checkout/{escape(checkout_session_id)}/pay/mock?outcome=failed"><button {disabled} type="submit">余额不足</button></form>
                <form method="post" action="/api/checkout/{escape(checkout_session_id)}/pay/mock?outcome=cancelled"><button {disabled} type="submit">取消支付</button></form>
                <form method="post" action="/api/checkout/{escape(checkout_session_id)}/pay/mock?outcome=timeout"><button {disabled} type="submit">支付超时</button></form>
              </div>
            </aside>
          </section>
        </main>
        """
        return self._page_shell("ShopGuide 沙箱结算台", body)

    def render_result_html(self, checkout_session_id: str) -> str:
        session = self.get_session(checkout_session_id)
        if not session:
            return self._page_shell("支付结果", "<main><h1>没有找到结算会话</h1></main>")
        order = self.orders.get(session.order_id or "")
        if order:
            deeplink = f"shopguide://checkout/success?order_id={escape(order.order_id)}"
            body = f"""
            <main class="result">
              <p class="eyebrow">Sandbox payment completed</p>
              <h1>支付成功</h1>
              <p>订单 {escape(order.order_id)} 已标记为 PAID_TEST，App 可以查询订单状态。</p>
              <a class="pay" href="{deeplink}">返回 ShopGuide App</a>
              <a class="secondary" href="/api/orders/{escape(order.order_id)}">查看订单 JSON</a>
            </main>
            """
        else:
            reason = escape(session.failure_reason or "沙箱支付未完成")
            body = f"""
            <main class="result">
              <p class="eyebrow">Sandbox payment result</p>
              <h1>支付未完成</h1>
              <p>{reason}</p>
              <a class="secondary" href="/checkout/{escape(checkout_session_id)}">返回结算台</a>
            </main>
            """
        return self._page_shell("支付结果", body)

    def _active_session_or_raise(self, checkout_session_id: str) -> CheckoutSession:
        session = self.get_session(checkout_session_id)
        if not session:
            raise ValueError("结算会话不存在")
        if session.expires_at < datetime.now(timezone.utc):
            session.status = "EXPIRED"
            raise ValueError("结算会话已过期")
        if session.status != "CREATED":
            raise ValueError("结算会话已处理")
        return session

    def _build_order(self, session: CheckoutSession) -> OrderState:
        order = OrderState(
            order_id=f"SGPAY{datetime.now().strftime('%Y%m%d')}{uuid4().hex[:8].upper()}",
            session_id=session.cart_snapshot.session_id,
            address=session.address,
            items=[
                OrderItem(
                    product_id=item.product.product_id,
                    title=item.product.title,
                    unit_price=item.unit_price,
                    quantity=item.quantity,
                    subtotal=round(item.unit_price * item.quantity, 2),
                    sku_id=item.selected_sku.sku_id if item.selected_sku else None,
                    sku_text=self._sku_text(item),
                )
                for item in session.cart_snapshot.items
            ],
            total_price=session.cart_snapshot.total_price,
            status="paid",
            payment_status="PAID_TEST",
            payment_provider="mock",
            checkout_session_id=session.checkout_session_id,
            paid_at=datetime.now(timezone.utc).isoformat(),
        )
        order.post_purchase_recommendations = self.cart.post_purchase.recommendations_for_order(order)
        return order

    def _review(self, cart_state: CartState) -> list[str]:
        item_count = sum(item.quantity for item in cart_state.items)
        review = [
            f"购物车共 {item_count} 件商品，总价 ¥{cart_state.total_price:.0f}。",
            "所有商品、SKU 和价格来自当前本地商品库快照。",
        ]
        sourced = sum(1 for item in cart_state.items if item.product.source_url)
        if sourced:
            review.append(f"{sourced} 件商品带公开来源，可在详情中核验。")
        low_review = [item.product.title[:14] for item in cart_state.items if item.product.review_count == 0]
        if low_review:
            review.append("注意：" + "、".join(low_review[:2]) + " 评论证据不足。")
        skus = [item for item in cart_state.items if item.selected_sku]
        if skus:
            review.append(f"{len(skus)} 个条目已锁定具体 SKU，支付后按该规格生成测试订单。")
        return review

    def _item_row(self, item: CartItem) -> str:
        image_url = item.selected_sku.image_url if item.selected_sku and item.selected_sku.image_url else item.product.image_url
        sku_text = escape(self._sku_text(item) or "默认规格")
        title = escape(item.product.title)
        brand = escape(item.product.brand)
        source = "公开来源" if item.product.source_url else item.product.source_name
        return f"""
        <article class="item">
          <img src="{escape(image_url)}" alt="{title}">
          <div>
            <h3>{title}</h3>
            <p>{brand}</p>
            <p>{sku_text}</p>
            <span>{escape(source)}</span>
          </div>
          <strong>¥{item.unit_price:.0f} x {item.quantity}</strong>
        </article>
        """

    def _sku_text(self, item: CartItem) -> str | None:
        if not item.selected_sku:
            return None
        return " / ".join(str(value) for value in item.selected_sku.properties.values())

    def _page_shell(self, title: str, body: str) -> str:
        return dedent(f"""\
        <!doctype html>
        <html lang="zh-CN">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>{escape(title)}</title>
          <style>
            :root {{ color-scheme: light dark; --accent:#0f9fb0; --ink:#111827; --muted:#64748b; --line:rgba(15,23,42,.12); --panel:rgba(255,255,255,.82); }}
            * {{ box-sizing:border-box; }}
            body {{ margin:0; font-family:"PingFang SC","Hiragino Sans GB","Heiti SC","Noto Sans CJK SC","Microsoft YaHei",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:linear-gradient(180deg,#f8fbfc,#edf5f6); color:var(--ink); }}
            .layout {{ width:min(1120px,100%); margin:0 auto; padding:32px 18px 48px; }}
            .hero {{ display:flex; justify-content:space-between; gap:18px; align-items:flex-end; padding:18px 0 22px; }}
            .eyebrow {{ margin:0 0 8px; color:var(--accent); font-weight:700; font-size:13px; letter-spacing:.02em; }}
            h1 {{ margin:0; font-size:34px; line-height:1.08; }}
            h2 {{ margin:0 0 14px; font-size:18px; }}
            .notice {{ margin:10px 0 0; color:var(--muted); }}
            .status {{ padding:10px 12px; border:1px solid var(--line); border-radius:8px; background:var(--panel); white-space:nowrap; }}
            .grid {{ display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:18px; align-items:start; }}
            .panel {{ border:1px solid var(--line); border-radius:8px; background:var(--panel); box-shadow:0 16px 44px rgba(15,23,42,.08); padding:16px; backdrop-filter:blur(18px); }}
            .items {{ display:grid; gap:12px; }}
            .item {{ display:grid; grid-template-columns:92px minmax(0,1fr) auto; gap:14px; align-items:center; padding:12px; border:1px solid var(--line); border-radius:8px; background:rgba(255,255,255,.58); }}
            .item img {{ width:92px; height:92px; object-fit:cover; border-radius:8px; background:#eef2f7; }}
            .item h3 {{ margin:0 0 6px; font-size:15px; line-height:1.3; }}
            .item p {{ margin:3px 0; color:var(--muted); font-size:13px; }}
            .item span {{ display:inline-block; margin-top:4px; color:var(--accent); font-size:12px; font-weight:700; }}
            .summary ul {{ margin:0 0 16px; padding-left:20px; color:#334155; line-height:1.65; }}
            .address,.total {{ display:flex; justify-content:space-between; gap:12px; padding:12px 0; border-top:1px solid var(--line); }}
            .total strong {{ font-size:28px; color:#dc2626; }}
            button,.pay,.secondary {{ width:100%; border:0; border-radius:8px; padding:13px 14px; font-family:inherit; font-weight:800; font-size:15px; text-align:center; text-decoration:none; display:block; cursor:pointer; }}
            .pay {{ background:var(--accent); color:white; margin-top:12px; }}
            .secondary,.fail-actions button {{ background:#e2e8f0; color:#0f172a; }}
            .fail-actions {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin-top:10px; }}
            .fail-actions button {{ font-size:12px; padding:10px 8px; }}
            button:disabled {{ opacity:.45; cursor:not-allowed; }}
            .result {{ width:min(680px,100%); margin:0 auto; min-height:100vh; display:grid; align-content:center; padding:24px; }}
            .result p {{ color:var(--muted); line-height:1.7; }}
            .result .secondary {{ margin-top:10px; }}
            @media (max-width:820px) {{ .hero,.grid {{ display:block; }} .status,.summary {{ margin-top:14px; }} .item {{ grid-template-columns:74px minmax(0,1fr); }} .item img {{ width:74px; height:74px; }} .item strong {{ grid-column:2; }} h1 {{ font-size:30px; }} }}
            @media (prefers-color-scheme: dark) {{ :root {{ --ink:#f8fafc; --muted:#94a3b8; --line:rgba(226,232,240,.16); --panel:rgba(15,23,42,.76); }} body {{ background:linear-gradient(180deg,#071114,#0f1720); }} .item {{ background:rgba(15,23,42,.56); }} .secondary,.fail-actions button {{ background:#1e293b; color:#e2e8f0; }} .summary ul {{ color:#cbd5e1; }} }}
          </style>
        </head>
        <body>{body}</body>
        </html>
        """).lstrip()

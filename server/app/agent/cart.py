from __future__ import annotations

import threading
from datetime import datetime
from uuid import uuid4

from app.models.schemas import CartItem, CartState, OrderItem, OrderState, Product, SKU
from app.agent.post_purchase import PostPurchaseRecommender
from app.rag.product_repository import ProductRepository


class CartService:
    def __init__(self, products: ProductRepository) -> None:
        self.products = products
        self.post_purchase = PostPurchaseRecommender(products)
        self._items: dict[str, dict[str, int]] = {}
        self._lock = threading.RLock()

    def add(self, session_id: str, product_id: str, quantity: int = 1, sku_id: str | None = None) -> CartState:
        with self._lock:
            product = self._product_or_raise(product_id)
            sku = self._selected_sku(product, sku_id)
            session = self._items.setdefault(session_id, {})
            line_id = self._line_id(product.product_id, sku.sku_id if sku else None)
            next_quantity = max(1, session.get(line_id, 0) + quantity)
            self._ensure_available(product, next_quantity)
            session[line_id] = next_quantity
            return self.state(session_id)

    def update(self, session_id: str, product_id: str, quantity: int, sku_id: str | None = None) -> CartState:
        with self._lock:
            product = self._product_or_raise(product_id)
            sku = self._selected_sku(product, sku_id)
            line_id = self._line_id(product.product_id, sku.sku_id if sku else None)
            session = self._items.setdefault(session_id, {})
            if quantity <= 0:
                session.pop(line_id, None)
            else:
                self._ensure_available(product, quantity)
                session[line_id] = quantity
            return self.state(session_id)

    def remove(self, session_id: str, product_id: str, sku_id: str | None = None) -> CartState:
        with self._lock:
            product = self.products.get(product_id)
            sku = self._selected_sku(product, sku_id) if product else None
            line_id = self._line_id(product_id, sku.sku_id if sku else sku_id) if product else product_id
            self._items.setdefault(session_id, {}).pop(line_id, None)
            return self.state(session_id)

    def clear(self, session_id: str) -> CartState:
        with self._lock:
            self._items[session_id] = {}
            return self.state(session_id)

    def state(self, session_id: str) -> CartState:
        with self._lock:
            items: list[CartItem] = []
            for line_id, quantity in list(self._items.setdefault(session_id, {}).items()):
                product_id, sku_id = self._parse_line_id(line_id)
                product = self.products.get(product_id)
                if product:
                    sku = self._selected_sku(product, sku_id)
                    unit_price = sku.price if sku else product.base_price
                    items.append(
                        CartItem(
                            line_id=self._line_id(product.product_id, sku.sku_id if sku else None),
                            product=product,
                            quantity=quantity,
                            selected_sku=sku,
                            unit_price=unit_price,
                        )
                    )
            total = sum(item.unit_price * item.quantity for item in items)
            return CartState(session_id=session_id, items=items, total_price=round(total, 2))

    def checkout(self, session_id: str, address: str = "默认地址") -> OrderState:
        with self._lock:
            state = self.state(session_id)
            if not state.items:
                raise ValueError("购物车为空，无法下单")
            self.ensure_state_available(state)
            order = OrderState(
                order_id=f"SG{datetime.now().strftime('%Y%m%d')}{uuid4().hex[:8].upper()}",
                session_id=session_id,
                address=address,
                items=[
                    OrderItem(
                        product_id=item.product.product_id,
                        title=item.product.title,
                        unit_price=item.unit_price,
                        quantity=item.quantity,
                        subtotal=round(item.unit_price * item.quantity, 2),
                        sku_id=item.selected_sku.sku_id if item.selected_sku else None,
                        sku_text=self._sku_text(item.selected_sku),
                    )
                    for item in state.items
                ],
                total_price=state.total_price,
            )
            order.post_purchase_recommendations = self.post_purchase.recommendations_for_order(order)
            self.clear(session_id)
            return order

    def ensure_state_available(self, state: CartState) -> None:
        """Re-check current catalog stock for a cart/checkout snapshot.

        Cart items carry product snapshots for UI rendering, but checkout should
        validate against the current product repository right before order
        creation so stale cart snapshots cannot bypass stock constraints.
        """
        for item in state.items:
            current = self._product_or_raise(item.product.product_id)
            self._ensure_available(current, item.quantity)

    def _product_or_raise(self, product_id: str) -> Product:
        product = self.products.get(product_id)
        if not product:
            raise ValueError("Product not found")
        return product

    def _ensure_available(self, product: Product, quantity: int) -> None:
        if product.stock_status == "out_of_stock" or product.inventory_count <= 0:
            raise ValueError(f"{product.title} 暂时无货，无法加入购物车或下单")
        if quantity > product.inventory_count:
            raise ValueError(f"{product.title} 库存仅剩 {product.inventory_count} 件，请调整数量")

    def _selected_sku(self, product: Product, sku_id: str | None) -> SKU | None:
        if sku_id:
            sku = next((sku for sku in product.skus if sku.sku_id == sku_id), None)
            if not sku:
                raise ValueError("SKU not found")
            return sku
        return product.skus[0] if product.skus else None

    def _line_id(self, product_id: str, sku_id: str | None) -> str:
        return f"{product_id}::{sku_id}" if sku_id else product_id

    def _parse_line_id(self, line_id: str) -> tuple[str, str | None]:
        if "::" not in line_id:
            return line_id, None
        product_id, sku_id = line_id.split("::", 1)
        return product_id, sku_id or None

    def _sku_text(self, sku: SKU | None) -> str | None:
        if not sku:
            return None
        return " / ".join(str(value) for value in sku.properties.values())

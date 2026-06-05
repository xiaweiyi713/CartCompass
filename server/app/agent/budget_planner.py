from __future__ import annotations

import re
from dataclasses import dataclass

from app.agent.constraint_parser import ConstraintParser
from app.agent.travel_intent import parse_travel_context
from app.agent.user_profile import UserProfileService
from app.models.schemas import Product, ShoppingPlan, ShoppingPlanItem
from app.observability import observability
from app.rag.product_repository import ProductRepository, SearchConstraints


@dataclass(frozen=True)
class PlanSlot:
    role: str
    query: str
    category: str
    sub_category: str | None
    allocation: float
    required: bool = True


class BudgetPlanner:
    def __init__(self, products: ProductRepository, parser: ConstraintParser, profiles: UserProfileService) -> None:
        self.products = products
        self.parser = parser
        self.profiles = profiles

    def can_plan(self, message: str) -> bool:
        compact = re.sub(r"[\s，。！？,.!?]", "", message)
        travel = parse_travel_context(message)
        has_budget = self._budget(message) is not None or "预算" in compact
        has_plan_word = any(term in compact for term in ["配一套", "套装", "方案", "清单", "全套", "组合", "一套"])
        travel_needs_plan = travel.is_travel and any(term in compact for term in ["应该买什么", "买什么", "准备什么", "需要买什么", "带什么"])
        has_scene = travel.is_travel or any(term in compact for term in ["通勤", "开学"])
        return has_budget and (has_plan_word or travel_needs_plan) and has_scene

    def build(self, user_id: str, message: str) -> ShoppingPlan | None:
        budget = self._budget(message) or 1000.0
        slots = self._slots(message)
        picked: list[ShoppingPlanItem] = []
        used_ids: set[str] = set()
        total = 0.0

        for slot in slots:
            slot_budget = max(49.0, budget * slot.allocation)
            product = self._best_product(user_id, slot, slot_budget, used_ids)
            if not product:
                continue
            used_ids.add(product.product_id)
            total += product.base_price
            picked.append(
                ShoppingPlanItem(
                    role=slot.role,
                    product=product,
                    reason=self._item_reason(slot, product, slot_budget),
                    optional=not slot.required,
                )
            )

        while total > budget and len(picked) > 2:
            removable = next((item for item in reversed(picked) if item.optional), picked[-1])
            picked.remove(removable)
            total = sum(item.product.base_price for item in picked)

        upgrades = self._upgrade_options(user_id, message, budget, total, used_ids, slots)
        remaining = round(budget - total, 2)
        plan = ShoppingPlan(
            title=self._title(message, budget),
            budget=budget,
            total_price=round(total, 2),
            remaining_budget=remaining,
            items=picked,
            upgrade_options=upgrades,
            notes=self._notes(message, budget, total, picked),
        )
        observability.increment("shopping_plan_requests")
        observability.add_current_step(
            "shopping_plan",
            {
                "budget": budget,
                "total_price": plan.total_price,
                "remaining_budget": plan.remaining_budget,
                "item_product_ids": [item.product.product_id for item in plan.items],
                "upgrade_product_ids": [item.product.product_id for item in plan.upgrade_options],
            },
        )
        return plan

    def _best_product(self, user_id: str, slot: PlanSlot, slot_budget: float, used_ids: set[str]) -> Product | None:
        constraints = SearchConstraints(
            category=slot.category,
            sub_category=slot.sub_category,
            max_price=slot_budget,
        )
        constraints = self.profiles.apply_to_constraints(user_id, constraints)
        query = f"{slot.query} {slot.role}"
        products = [product for product in self.products.search(query, constraints, limit=8) if product.product_id not in used_ids]
        if products:
            return products[0]
        relaxed = SearchConstraints(category=slot.category, sub_category=slot.sub_category)
        relaxed = self.profiles.apply_to_constraints(user_id, relaxed)
        return next((product for product in self.products.search(query, relaxed, limit=8) if product.product_id not in used_ids), None)

    def _upgrade_options(
        self,
        user_id: str,
        message: str,
        budget: float,
        total: float,
        used_ids: set[str],
        slots: list[PlanSlot],
    ) -> list[ShoppingPlanItem]:
        remaining = budget - total
        if remaining < 80:
            return []
        upgrades: list[ShoppingPlanItem] = []
        for slot in slots:
            constraints = SearchConstraints(category=slot.category, sub_category=slot.sub_category, min_price=max(80, remaining * 0.35), max_price=remaining + budget * slot.allocation)
            constraints = self.profiles.apply_to_constraints(user_id, constraints)
            for product in self.products.search(f"{message} 升级 {slot.query}", constraints, limit=4):
                if product.product_id in used_ids:
                    continue
                used_ids.add(product.product_id)
                upgrades.append(
                    ShoppingPlanItem(
                        role=f"{slot.role}升级项",
                        product=product,
                        reason=f"预算还剩约 {remaining:.0f} 元时可升级这一项，匹配 {slot.role} 场景。",
                        optional=True,
                    )
                )
                break
            if len(upgrades) >= 2:
                break
        return upgrades

    def _slots(self, message: str) -> list[PlanSlot]:
        travel = parse_travel_context(message)
        if travel.is_travel or any(term in message for term in ["防晒", "旅行", "度假", "出行"]):
            prefix = travel.query_prefix
            return [
                PlanSlot("高倍防晒", f"{prefix} 防晒 防水 清爽 油皮", "美妆护肤", "防晒", 0.18),
                PlanSlot("轻量衣物/背包", f"{prefix} 户外 防晒衣 背包 速干 轻量", "服饰运动", None, 0.26),
                PlanSlot("出行充电", f"{prefix} 快充 充电宝 轻量", "数码电子", "充电宝", 0.22),
                PlanSlot("路上补能", f"{prefix} 零食 坚果 独立小包装 补能", "食品饮料", "坚果", 0.12, required=False),
            ]
        if any(term in message for term in ["通勤", "上班"]):
            return [
                PlanSlot("通勤耳机", "通勤 降噪 蓝牙耳机", "数码电子", "耳机", 0.36),
                PlanSlot("快充补电", "快充 充电器 充电宝", "数码电子", None, 0.24),
                PlanSlot("轻量服饰", "通勤 轻量 百搭", "服饰运动", "运动服饰", 0.24, required=False),
            ]
        return [
            PlanSlot("核心商品", message, "数码电子", None, 0.55),
            PlanSlot("配件补充", f"{message} 快充 配件", "数码电子", None, 0.25, required=False),
        ]

    def _budget(self, message: str) -> float | None:
        patterns = [
            r"(\d+(?:\.\d+)?)\s*(?:元|块|rmb)?\s*(?:预算|以内|以下|内|之内)",
            r"预算\s*(\d+(?:\.\d+)?)",
            r"不超过\s*(\d+(?:\.\d+)?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.I)
            if match:
                return float(match.group(1))
        return None

    def _title(self, message: str, budget: float) -> str:
        travel = parse_travel_context(message)
        if travel.is_travel:
            return f"{travel.destination}旅行 {budget:.0f} 元预算方案"
        if "通勤" in message:
            return f"通勤装备 {budget:.0f} 元预算方案"
        return f"{budget:.0f} 元预算组合方案"

    def _item_reason(self, slot: PlanSlot, product: Product, slot_budget: float) -> str:
        facts = [f"用于{slot.role}", f"价格约 {product.base_price:.0f} 元"]
        if product.base_price <= slot_budget:
            facts.append(f"落在该项预算 {slot_budget:.0f} 元内")
        if product.match_reasons:
            facts.append(product.match_reasons[0])
        elif product.highlights:
            facts.append(product.highlights[0])
        return "；".join(facts)

    def _notes(self, message: str, budget: float, total: float, items: list[ShoppingPlanItem]) -> list[str]:
        notes = [
            "方案只使用当前商品库里的可验证商品，价格按商品库基础价估算。",
            "每个必需类目最多选 1 件，避免同类重复堆叠。",
        ]
        if total <= budget:
            notes.append(f"当前总价约 {total:.0f} 元，未超过 {budget:.0f} 元预算。")
        else:
            notes.append(f"当前总价约 {total:.0f} 元，略超预算，可删去可选项或降低单项预算。")
        if any(item.product.risk_flags for item in items):
            notes.append("部分商品存在评论不足、来源不足或接近预算上限等风险，详情页会继续展示。")
        return notes

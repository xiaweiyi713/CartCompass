from __future__ import annotations

from dataclasses import dataclass

from app.agent.constraint_parser import ConstraintParser
from app.models.schemas import Product
from app.models.schemas import WeatherContext
from app.observability import observability
from app.rag.product_repository import ProductRepository, SearchConstraints
from app.travel.destination_context import DestinationContext, DestinationContextTool
from app.travel.scenario_rules import ScenarioNeed, ScenarioRule, load_scenario_rules


@dataclass(frozen=True)
class PlannedTravelNeed:
    need: str
    category: str
    sub_category: str | None
    priority: int
    query: str
    reason: str
    quota: int = 1
    rule_id: str = ""
    scene_name: str = ""

    @property
    def key(self) -> tuple[str, str | None]:
        return self.category, self.sub_category


@dataclass(frozen=True)
class TravelBundle:
    context: DestinationContext
    scene_names: tuple[str, ...]
    needs: tuple[PlannedTravelNeed, ...]
    products: tuple[Product, ...]
    clarification: str | None = None


class TravelNeedPlanner:
    def __init__(self, products: ProductRepository, parser: ConstraintParser) -> None:
        self.products = products
        self.parser = parser
        self.context_tool = DestinationContextTool()

    def build(
        self,
        message: str,
        llm_plan: dict | None = None,
        limit: int = 5,
        weather_context: WeatherContext | None = None,
    ) -> TravelBundle:
        context = self.context_tool.build(message, llm_plan=llm_plan)
        rules = self._match_rules(context)
        needs = self._planned_needs(context, rules, llm_plan, weather_context)
        products = self._retrieve_diverse_bundle(message, context, needs, limit=limit)
        observability.add_current_step(
            "travel_planner",
            {
                "destination": context.destination,
                "attributes": list(context.attributes),
                "activities": list(context.likely_activities),
                "risks": list(context.risks),
                "packing_needs": list(context.packing_needs),
                "weather_tags": list(weather_context.implications.tags) if weather_context else [],
                "weather_needs": list(weather_context.implications.shopping_needs) if weather_context else [],
                "rules": [rule.rule_id for rule in rules],
                "needs": [need.__dict__ for need in needs[:8]],
                "product_ids": [product.product_id for product in products],
            },
        )
        return TravelBundle(
            context=context,
            scene_names=tuple(rule.scene_name for rule in rules),
            needs=tuple(needs),
            products=tuple(products),
            clarification=context.clarification_question,
        )

    def _match_rules(self, context: DestinationContext) -> list[ScenarioRule]:
        signals = context.signals
        rules_by_id = {rule.rule_id: rule for rule in load_scenario_rules()}
        if signals & {"商务", "出差", "会议", "办公"}:
            return [rules_by_id["business_trip"]]
        if signals & {"亲子", "家庭", "带娃"}:
            return [rules_by_id["family_trip"]]
        scored = [(rule.score(signals), rule) for rule in load_scenario_rules()]
        scored = [(score, rule) for score, rule in scored if score > 0]
        scored.sort(key=lambda item: (-item[0], item[1].rule_id))
        if not scored:
            return [rules_by_id["city_walk"]]
        top_score = scored[0][0]
        selected = [rule for score, rule in scored if score >= max(2, top_score - 2)][:2]
        if not selected:
            selected = [scored[0][1]]
        return selected

    def _planned_needs(
        self,
        context: DestinationContext,
        rules: list[ScenarioRule],
        llm_plan: dict | None,
        weather_context: WeatherContext | None = None,
    ) -> list[PlannedTravelNeed]:
        needs: list[PlannedTravelNeed] = []
        seen: set[tuple[str, str | None]] = set()
        avoid = {item for rule in rules for item in rule.avoid_categories}

        for rule in rules:
            for item in sorted(rule.recommended_categories, key=lambda need: need.priority):
                if item.sub_category in avoid or item.category in avoid:
                    continue
                planned = self._planned_from_rule(item, rule)
                if planned.key in seen:
                    continue
                seen.add(planned.key)
                needs.append(planned)

        for item in self._needs_from_llm_plan(llm_plan):
            if item.key in seen:
                continue
            seen.add(item.key)
            needs.append(item)

        for item in self._needs_from_weather(weather_context):
            if item.key in seen:
                continue
            seen.add(item.key)
            needs.append(item)

        # Keep rule/LLM/weather source order so live weather does not crowd out
        # the core scenario bundle when only five product cards are shown.
        return needs[:8]

    def _planned_from_rule(self, need: ScenarioNeed, rule: ScenarioRule) -> PlannedTravelNeed:
        return PlannedTravelNeed(
            need=need.need,
            category=need.category,
            sub_category=need.sub_category,
            priority=need.priority,
            query=need.query,
            reason=need.reason,
            quota=need.quota,
            rule_id=rule.rule_id,
            scene_name=rule.scene_name,
        )

    def _needs_from_llm_plan(self, llm_plan: dict | None) -> list[PlannedTravelNeed]:
        if not llm_plan:
            return []
        allowed = {
            ("美妆护肤", "防晒"),
            ("美妆护肤", "面霜"),
            ("美妆护肤", "精华"),
            ("服饰运动", "帽子"),
            ("服饰运动", "背包"),
            ("服饰运动", "徒步鞋"),
            ("服饰运动", "速干T恤"),
            ("服饰运动", "运动服饰"),
            ("服饰运动", "运动装备"),
            ("服饰运动", "运动鞋"),
            ("数码电子", "充电设备"),
            ("食品饮料", "功能饮料"),
            ("食品饮料", "咖啡"),
            ("食品饮料", "坚果/零食"),
            ("食品饮料", "方便食品"),
        }
        output: list[PlannedTravelNeed] = []
        for raw in llm_plan.get("slots", [])[:5]:
            if not isinstance(raw, dict):
                continue
            category = raw.get("category")
            sub_category = raw.get("sub_category")
            if (category, sub_category) not in allowed:
                continue
            query = str(raw.get("search_terms") or raw.get("role") or "").strip()
            if not query:
                continue
            output.append(
                PlannedTravelNeed(
                    need=str(raw.get("role") or sub_category or category)[:24],
                    category=str(category),
                    sub_category=str(sub_category) if sub_category else None,
                    priority=4,
                    query=query[:120],
                    reason=str(raw.get("reason") or "模型补充的场景需求")[:80],
                    quota=1,
                    rule_id="llm_context",
                    scene_name="模型补充",
                )
            )
        return output

    def _needs_from_weather(self, weather_context: WeatherContext | None) -> list[PlannedTravelNeed]:
        if not weather_context:
            return []
        mapping = {
            "防晒": ("美妆护肤", "防晒", "防晒霜 高倍数 户外", "天气显示紫外线或高温风险，优先补充防晒"),
            "防晒霜": ("美妆护肤", "防晒", "防晒霜 高倍数 户外", "天气显示紫外线偏强，优先补充防晒霜"),
            "防晒衣": ("服饰运动", "速干T恤", "防晒衣 速干 透气", "天气显示紫外线偏强，适合物理防晒"),
            "墨镜": ("服饰运动", "帽子", "帽子 遮阳 户外", "当前商品库缺少墨镜时，用遮阳帽覆盖护眼防晒需求"),
            "透气衣物": ("服饰运动", "速干T恤", "速干 透气 轻量", "高温天气下优先轻量透气衣物"),
            "补水": ("食品饮料", "功能饮料", "补水 功能饮料 户外", "高温出行需要补水和补能"),
            "雨具": ("服饰运动", "运动装备", "防水 雨具 户外", "降雨概率较高，优先考虑防水用品"),
            "防水": ("服饰运动", "背包", "防水 收纳 背包", "降雨或潮湿环境需要防水收纳"),
            "防滑": ("服饰运动", "徒步鞋", "防滑 徒步鞋 户外", "湿滑或冰雪环境需要防滑鞋"),
            "保暖": ("服饰运动", "运动服饰", "保暖 防风 外套", "低温天气需要保暖衣物"),
            "防风": ("服饰运动", "运动服饰", "防风 外套 户外", "低温或大风环境需要防风层"),
            "保湿": ("美妆护肤", "面霜", "保湿 面霜 干燥", "干冷天气容易皮肤干燥"),
        }
        output: list[PlannedTravelNeed] = []
        for need in weather_context.implications.shopping_needs:
            if need not in mapping:
                continue
            category, sub_category, query, reason = mapping[need]
            output.append(
                PlannedTravelNeed(
                    need=f"天气需求：{need}",
                    category=category,
                    sub_category=sub_category,
                    priority=2,
                    query=query,
                    reason=reason,
                    quota=1,
                    rule_id="weather_context",
                    scene_name="实时天气",
                )
            )
        return output

    def _retrieve_diverse_bundle(
        self,
        message: str,
        context: DestinationContext,
        needs: list[PlannedTravelNeed],
        limit: int,
    ) -> list[Product]:
        selected: list[Product] = []
        seen: set[str] = set()
        spent = 0.0
        budget = context.budget
        for need in needs:
            for _ in range(max(1, need.quota)):
                if len(selected) >= limit:
                    return selected
                product = self._pick_for_need(message, context, need, seen, budget, spent)
                if not product:
                    continue
                seen.add(product.product_id)
                spent += product.base_price
                self._annotate_product(product, context, need)
                selected.append(product)
        return selected

    def _pick_for_need(
        self,
        message: str,
        context: DestinationContext,
        need: PlannedTravelNeed,
        seen: set[str],
        budget: float | None,
        spent: float,
    ) -> Product | None:
        query = " ".join(
            [
                context.destination,
                " ".join(context.attributes),
                " ".join(context.packing_needs),
                need.need,
                need.query,
            ]
        )
        candidates = self._search_need(query, need, limit=8)
        if not candidates and need.sub_category:
            relaxed = PlannedTravelNeed(
                need=need.need,
                category=need.category,
                sub_category=None,
                priority=need.priority,
                query=need.query,
                reason=need.reason,
                quota=need.quota,
                rule_id=need.rule_id,
                scene_name=need.scene_name,
            )
            candidates = self._search_need(query, relaxed, limit=8)
        candidates = [product for product in candidates if product.product_id not in seen]
        if not candidates:
            return None
        if budget:
            affordable = [product for product in candidates if spent + product.base_price <= budget]
            if affordable:
                return affordable[0]
            if need.priority <= 1:
                return min(candidates, key=lambda product: product.base_price)
            return None
        return candidates[0]

    def _search_need(self, query: str, need: PlannedTravelNeed, limit: int) -> list[Product]:
        constraints = self.parser.parse(query)
        constraints.category = need.category
        constraints.sub_category = need.sub_category
        constraints.include_terms = []
        return self.products.search(query, constraints, limit=limit)

    def _annotate_product(self, product: Product, context: DestinationContext, need: PlannedTravelNeed) -> None:
        product.match_reasons = [
            f"旅行需求：{need.need}",
            f"场景属性：{'、'.join(context.attributes[:4])}",
            f"规划依据：{need.reason}",
            *product.match_reasons[:3],
        ]
        product.reason = f"{product.reason}；用于{need.need}：{need.reason}"

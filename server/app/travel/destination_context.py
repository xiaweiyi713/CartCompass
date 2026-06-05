from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agent.travel_intent import parse_travel_context


@dataclass(frozen=True)
class DestinationContext:
    destination: str
    travel_type: str
    attributes: tuple[str, ...]
    likely_activities: tuple[str, ...]
    risks: tuple[str, ...]
    packing_needs: tuple[str, ...]
    need_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = 0.72
    season: str | None = None
    budget: float | None = None

    @property
    def signals(self) -> set[str]:
        return set(self.attributes) | set(self.likely_activities) | set(self.risks) | set(self.packing_needs)


DESTINATION_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "三亚": ("海滨", "热带", "高温", "潮湿", "强紫外线", "度假"),
    "青岛": ("海滨", "城市漫游", "潮湿", "强紫外线"),
    "厦门": ("海滨", "城市漫游", "潮湿", "强紫外线"),
    "冲绳": ("海滨", "热带", "潮湿", "强紫外线", "海岛"),
    "哈尔滨": ("寒冷", "冰雪", "低温", "干燥", "大风"),
    "东北": ("寒冷", "冰雪", "低温", "干燥"),
    "北海道": ("寒冷", "冰雪", "低温", "城市观光"),
    "新疆": ("高原", "干燥", "强紫外线", "昼夜温差", "长途", "自驾"),
    "西藏": ("高原", "干燥", "强紫外线", "昼夜温差"),
    "拉萨": ("高原", "干燥", "强紫外线", "昼夜温差"),
    "青海": ("高原", "干燥", "强紫外线", "昼夜温差"),
    "川西": ("高原", "山地", "强紫外线", "昼夜温差", "徒步"),
    "甘肃": ("干燥", "强紫外线", "沙漠", "长途"),
    "成都": ("城市漫游", "美食", "湿润", "多雨", "休闲"),
    "重庆": ("城市漫游", "美食", "湿润", "多雨", "山城"),
    "云南": ("高海拔", "城市漫游", "强紫外线", "温差适中"),
    "张家界": ("山地", "徒步", "多雨", "湿润", "户外"),
    "桂林": ("城市漫游", "多雨", "湿润", "户外"),
    "上海": ("城市漫游", "商务", "通勤", "湿润"),
    "北京": ("城市漫游", "历史文化", "长时间步行"),
    "东京": ("城市漫游", "境外", "长时间步行", "拍照"),
    "大阪": ("城市漫游", "境外", "美食", "长时间步行"),
    "京都": ("城市漫游", "境外", "长时间步行", "拍照"),
    "日本": ("城市漫游", "境外", "长时间步行", "拍照"),
    "柏林": ("城市漫游", "境外", "长时间步行", "拍照", "多雨"),
    "德国": ("城市漫游", "境外", "长时间步行", "拍照", "多雨"),
    "巴黎": ("城市漫游", "境外", "长时间步行", "拍照"),
    "法国": ("城市漫游", "境外", "长时间步行", "拍照"),
    "罗马": ("城市漫游", "境外", "长时间步行", "拍照"),
    "意大利": ("城市漫游", "境外", "长时间步行", "拍照"),
    "伦敦": ("城市漫游", "境外", "长时间步行", "拍照", "多雨"),
    "英国": ("城市漫游", "境外", "长时间步行", "拍照", "多雨"),
    "瑞士": ("城市漫游", "境外", "长时间步行", "拍照", "山地"),
    "曼谷": ("热带", "高温", "潮湿", "城市漫游", "美食"),
    "新加坡": ("热带", "高温", "潮湿", "城市漫游", "境外"),
}


class DestinationContextTool:
    def build(self, message: str, llm_plan: dict | None = None) -> DestinationContext:
        travel = parse_travel_context(message)
        compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
        destination = self._destination(message, travel.destination)
        attributes = list(DESTINATION_ATTRIBUTES.get(destination, ()))
        attributes.extend(self._attributes_from_text(compact, travel.scenario))
        if not attributes:
            attributes.extend(["城市漫游", "通用旅行"])

        travel_type = self._travel_type(compact, travel.scenario)
        activities = self._activities(attributes, compact)
        risks = self._risks(attributes)
        needs = self._packing_needs(attributes, compact)
        broad = destination in {"日本", "欧洲", "美国"} and not any(
            term in compact for term in ("北海道", "冲绳", "东京", "大阪", "京都", "滑雪", "海岛", "商务", "出差")
        )
        question = None
        if broad:
            question = self._broad_destination_question(destination)

        return DestinationContext(
            destination=destination,
            travel_type=travel_type,
            attributes=tuple(dict.fromkeys(attributes)),
            likely_activities=tuple(dict.fromkeys(activities)),
            risks=tuple(dict.fromkeys(risks)),
            packing_needs=tuple(dict.fromkeys(needs)),
            need_clarification=broad,
            clarification_question=question,
            confidence=0.86 if destination in DESTINATION_ATTRIBUTES else 0.62,
            season=self._season(compact),
            budget=self._budget(message),
        )

    def _destination(self, message: str, parsed_destination: str) -> str:
        for destination in DESTINATION_ATTRIBUTES:
            if destination.lower() in message.lower():
                return destination
        return parsed_destination if parsed_destination and parsed_destination != "旅行" else "旅行"

    def _broad_destination_question(self, destination: str) -> str:
        examples = {
            "日本": "北海道、冲绳或滑雪/海岛场景",
            "欧洲": "巴黎、罗马、瑞士或滑雪/海岛场景",
            "美国": "纽约、洛杉矶、夏威夷或国家公园场景",
        }
        return f"{destination}行程差异较大，我先按城市观光配一版；如果你去{examples.get(destination, '更具体的城市或特殊场景')}，我会再调整。"

    def _attributes_from_text(self, compact: str, scenario: str) -> list[str]:
        attrs: list[str] = []
        keyword_attrs = {
            ("海边", "海岛", "游泳", "沙滩"): ["海滨", "潮湿", "强紫外线"],
            ("高原", "拉萨", "西藏"): ["高原", "干燥", "强紫外线"],
            ("沙漠", "自驾", "长途"): ["干燥", "长途"],
            ("滑雪", "雪", "寒冷", "冰雪"): ["寒冷", "冰雪", "低温"],
            ("雨", "梅雨", "雨季"): ["多雨", "湿润"],
            ("出差", "商务", "会议"): ["商务", "出差", "通勤"],
            ("徒步", "露营", "爬山", "山地"): ["徒步", "户外", "山地"],
            ("亲子", "带娃", "小孩", "老人"): ["亲子", "家庭"],
        }
        for keywords, values in keyword_attrs.items():
            if any(keyword in compact for keyword in keywords):
                attrs.extend(values)
        if "海边" in scenario:
            attrs.extend(["海滨", "高温", "潮湿", "强紫外线"])
        if any(term in scenario for term in ("高原", "干燥")):
            attrs.extend(["高原", "干燥", "强紫外线"])
        if "寒冷" in scenario:
            attrs.extend(["寒冷", "低温", "干燥"])
        if "差旅" in scenario:
            attrs.extend(["商务", "出差"])
        if "城市" in scenario:
            attrs.extend(["城市漫游", "长时间步行"])
        return attrs

    def _travel_type(self, compact: str, scenario: str) -> str:
        if any(term in compact for term in ("出差", "商务")):
            return "商务出差"
        if any(term in compact for term in ("亲子", "带娃", "家庭")):
            return "亲子旅行"
        if any(term in compact for term in ("度假", "海边", "海岛")):
            return "度假"
        if any(term in compact for term in ("徒步", "露营", "自驾")):
            return "户外旅行"
        return scenario or "旅行"

    def _activities(self, attributes: list[str], compact: str) -> list[str]:
        attrs = set(attributes)
        activities: list[str] = []
        if attrs & {"海滨", "热带"}:
            activities.extend(["海边", "拍照", "户外步行"])
        if attrs & {"寒冷", "冰雪"}:
            activities.extend(["冰雪景区", "户外拍照"])
        if attrs & {"高原", "山地", "徒步"}:
            activities.extend(["徒步", "自驾", "户外景区"])
        if attrs & {"城市漫游", "美食", "商务"}:
            activities.extend(["城市漫游", "长时间步行", "拍照"])
        if "亲子" in compact:
            activities.append("照看儿童")
        return activities or ["出行", "拍照", "步行"]

    def _risks(self, attributes: list[str]) -> list[str]:
        attrs = set(attributes)
        risks: list[str] = []
        if attrs & {"强紫外线", "高温"}:
            risks.extend(["晒伤", "中暑"])
        if "潮湿" in attrs:
            risks.append("防水需求")
        if attrs & {"寒冷", "低温"}:
            risks.extend(["失温", "手机掉电快"])
        if "干燥" in attrs:
            risks.append("皮肤干裂")
        if attrs & {"多雨", "湿润"}:
            risks.extend(["降雨", "鞋包受潮"])
        if attrs & {"高原"}:
            risks.extend(["强紫外线", "昼夜温差"])
        if attrs & {"徒步", "山地"}:
            risks.append("防滑需求")
        return risks

    def _packing_needs(self, attributes: list[str], compact: str) -> list[str]:
        attrs = set(attributes)
        needs: list[str] = []
        if attrs & {"强紫外线", "高温", "海滨"}:
            needs.extend(["防晒", "透气"])
        if attrs & {"潮湿", "多雨"}:
            needs.extend(["防水", "收纳"])
        if attrs & {"寒冷", "低温"}:
            needs.extend(["保暖", "防滑", "保湿", "充电"])
        if attrs & {"干燥", "高原"}:
            needs.extend(["保湿", "防风", "补能"])
        if attrs & {"城市漫游", "美食", "商务"}:
            needs.extend(["轻便鞋", "随身包", "拍照补电"])
        if attrs & {"徒步", "山地"}:
            needs.extend(["防滑", "耐磨", "补能"])
        if "出差" in compact:
            needs.extend(["快充", "通勤收纳", "提神"])
        return needs or ["随身包", "补电", "轻便鞋"]

    def _season(self, compact: str) -> str | None:
        for season in ("春", "夏", "秋", "冬"):
            if season in compact:
                return season
        if any(term in compact for term in ("下周", "周末", "明天")):
            return "未指定具体季节"
        return None

    def _budget(self, message: str) -> float | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|预算)", message)
        return float(match.group(1)) if match else None

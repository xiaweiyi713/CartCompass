from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class ScenarioNeed:
    need: str
    category: str
    sub_category: str | None
    priority: int
    query: str
    reason: str
    quota: int = 1


@dataclass(frozen=True)
class ScenarioRule:
    rule_id: str
    scene_name: str
    triggers: tuple[str, ...]
    required_needs: tuple[str, ...]
    recommended_categories: tuple[ScenarioNeed, ...]
    avoid_categories: tuple[str, ...]

    def score(self, signals: set[str]) -> int:
        return sum(2 for trigger in self.triggers if trigger in signals) + sum(
            1 for need in self.required_needs if need in signals
        )


@lru_cache(maxsize=1)
def load_scenario_rules() -> tuple[ScenarioRule, ...]:
    path = Path(__file__).with_name("travel_scenario_rules.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rules: list[ScenarioRule] = []
    for raw in payload:
        rules.append(
            ScenarioRule(
                rule_id=raw["id"],
                scene_name=raw["scene_name"],
                triggers=tuple(raw.get("triggers", [])),
                required_needs=tuple(raw.get("required_needs", [])),
                recommended_categories=tuple(
                    ScenarioNeed(
                        need=item["need"],
                        category=item["category"],
                        sub_category=item.get("sub_category"),
                        priority=int(item.get("priority", 3)),
                        query=item["query"],
                        reason=item["reason"],
                        quota=int(item.get("quota", 1)),
                    )
                    for item in raw.get("recommended_categories", [])
                ),
                avoid_categories=tuple(raw.get("avoid_categories", [])),
            )
        )
    return tuple(rules)


from __future__ import annotations

from app.llm.schemas import ModelCapability


MODEL_CAPABILITIES: dict[str, ModelCapability] = {
    "deepseek-chat": ModelCapability(
        supports_stream=True,
        supports_json_mode=True,
        supports_tool_call=True,
        best_for=["answer_generation", "constraint_parsing", "travel_need_planning"],
        not_recommended_for=["vision"],
        max_context=64000,
    ),
    "deepseek-reasoner": ModelCapability(
        supports_stream=True,
        supports_json_mode="provider_dependent",
        supports_tool_call="provider_dependent",
        best_for=["checkout_review", "complex_comparison"],
        not_recommended_for=["high_volume_json_parsing", "vision"],
        max_context=64000,
    ),
    "doubao-seed-2.0-lite": ModelCapability(
        supports_stream=True,
        supports_json_mode="partial",
        supports_tool_call="partial",
        best_for=["cheap_routing", "chinese_answer"],
        not_recommended_for=["strict_json_without_validation"],
        max_context=None,
    ),
}


class ModelRouter:
    def capability(self, model: str | None) -> ModelCapability:
        if not model:
            return ModelCapability()
        return MODEL_CAPABILITIES.get(model, ModelCapability(supports_stream=True, best_for=["answer_generation"]))

    def temperature_for_task(self, task: str) -> float:
        return {
            "intent_classification": 0.0,
            "constraint_parsing": 0.0,
            "travel_need_planning": 0.1,
            "answer_generation": 0.2,
            "review_summary": 0.2,
            "checkout_review": 0.2,
        }.get(task, 0.2)


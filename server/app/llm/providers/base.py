from __future__ import annotations

from typing import Protocol

from app.agent.llm_client import LLMCallResult, LLMConfig


class LLMProvider(Protocol):
    async def chat(
        self,
        config: LLMConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> LLMCallResult:
        ...


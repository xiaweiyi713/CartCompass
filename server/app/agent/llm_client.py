from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, replace
from typing import AsyncIterator

import httpx

from app.config import (
    ANTHROPIC_BASE_URL,
    ANTHROPIC_MODEL,
    ARK_API_KEY,
    ARK_BASE_URL,
    ARK_MODEL,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LLM_DEFAULT_TIMEOUT_SECONDS,
)
from app.models.schemas import LLMConfigRequest, LLMStatus, LLMTestRequest, Product
from app.observability import observability
from app.rag.product_repository import SearchConstraints


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str | None = None
    api_key: str = ""
    base_url: str | None = None
    temperature: float = 0.2
    timeout_seconds: float = LLM_DEFAULT_TIMEOUT_SECONDS
    source: str = "env"

    @property
    def is_configured(self) -> bool:
        return self.provider != "disabled" and bool(self.api_key)


@dataclass(frozen=True)
class LLMCallResult:
    text: str
    provider: str
    model: str
    latency_ms: float
    usage: dict | None = None


class ArkLLMClient:
    """LLM Gateway used by the Agent.

    The class name is kept for compatibility with the existing orchestrator,
    but the implementation is now a provider-agnostic gateway. Runtime configs
    are intentionally in-memory only, so BYOK demo keys are not persisted by
    default.
    """

    def __init__(self) -> None:
        self.default_config = LLMConfig(
            provider="ark",
            model=ARK_MODEL,
            api_key=ARK_API_KEY,
            base_url=ARK_BASE_URL,
            source="env",
        )
        self._session_configs: dict[str, LLMConfig] = {}

    @property
    def is_configured(self) -> bool:
        return self.default_config.is_configured or any(config.is_configured for config in self._session_configs.values())

    @property
    def model(self) -> str | None:
        return self.default_config.model

    def status(self, session_id: str = "default") -> LLMStatus:
        config = self._config_for_session(session_id)
        return LLMStatus(
            configured=config.is_configured,
            provider=config.provider,
            model=config.model,
            base_url=self._safe_base_url(config.base_url),
            source=config.source,
            key_present=bool(config.api_key),
            key_hint=self._key_hint(config.api_key),
        )

    def configure(self, request: LLMConfigRequest) -> LLMStatus:
        config = self._config_from_request(request)
        self._session_configs[request.session_id] = config
        observability.increment("llm_config_updates")
        observability.add_current_step(
            "llm_config",
            {
                "session_id": request.session_id,
                "provider": config.provider,
                "model": config.model,
                "base_url": self._safe_base_url(config.base_url),
                "temporary": request.temporary,
                "key_present": bool(config.api_key),
            },
        )
        return self.status(request.session_id)

    def clear(self, session_id: str) -> LLMStatus:
        self._session_configs.pop(session_id, None)
        observability.increment("llm_config_clears")
        return self.status(session_id)

    async def test_connection(self, request: LLMTestRequest) -> dict:
        config = self._config_from_test_request(request)
        started_at = time.perf_counter()
        if not config.is_configured:
            return {
                "ok": False,
                "provider": config.provider,
                "model": config.model,
                "latency_ms": 0,
                "message": "模型未配置 API Key",
            }
        try:
            result = await self._chat(
                config,
                messages=[
                    {"role": "system", "content": "你是连接测试助手。"},
                    {"role": "user", "content": "只回复 OK，用于测试连接。"},
                ],
                temperature=request.temperature,
                max_tokens=16,
            )
        except LLMGatewayError as exc:
            return {
                "ok": False,
                "provider": config.provider,
                "model": config.model,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "message": str(exc),
            }
        return {
            "ok": True,
            "provider": result.provider,
            "model": result.model,
            "latency_ms": round(result.latency_ms, 2),
            "message": result.text[:80],
            "usage": result.usage or {},
        }

    async def recommendation_reply(
        self,
        user_message: str,
        products: list[Product],
        constraints: SearchConstraints,
        session_id: str = "default",
    ) -> str | None:
        config = self._config_for_session(session_id)
        if not config.is_configured:
            return None
        # Prompt contract for grounded recommendations:
        # the user message is paired with normalized constraints and a compact
        # `products` fact array generated by backend tools. The model is not asked
        # to search, price, infer stock, or invent policies; it can only turn this
        # bounded packet into natural Chinese wording, and the caller still runs
        # GroundingGuard before accepting the text.
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_message": user_message,
                        "constraints": asdict(constraints),
                        "products": [self._product_fact(product) for product in products],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            result = await self._chat(config, messages=messages, temperature=config.temperature, max_tokens=380)
        except LLMGatewayError:
            observability.increment("llm_gateway_failures")
            return None
        observability.increment("llm_gateway_success")
        observability.record_latency("llm_gateway_latency_ms", result.latency_ms)
        observability.add_current_step(
            "llm_gateway",
            {
                "provider": result.provider,
                "model": result.model,
                "latency_ms": round(result.latency_ms, 2),
                "usage": result.usage or {},
            },
        )
        return result.text

    async def travel_need_plan(self, user_message: str, session_id: str = "default") -> dict | None:
        config = self._config_for_session(session_id)
        if not config.is_configured:
            return None
        messages = [
            {
                "role": "system",
                "content": (
                    "你是电商出行导购的需求规划器。根据用户的旅行目的地和场景，输出可用于商品检索的 JSON。"
                    "不要推荐具体商品，不要编价格、库存或品牌。"
                    "只能从这些类目中选择：美妆护肤/防晒、面霜、精华；"
                    "服饰运动/帽子、背包、徒步鞋、速干T恤、运动服饰、运动装备、运动鞋；"
                    "数码电子/充电设备；食品饮料/功能饮料、咖啡、坚果/零食、方便食品。"
                    "输出 JSON 对象，字段：destination, scenario, intro_focus, slots。"
                    "slots 是 3-5 个对象，每个对象包含 role, category, sub_category, search_terms, reason。"
                    "search_terms 用中文关键词，适合检索商品库。只输出 JSON，不要 Markdown。"
                ),
            },
            {"role": "user", "content": user_message},
        ]
        try:
            result = await self._chat(config, messages=messages, temperature=0.1, max_tokens=420, response_format_json=True)
            plan = self._parse_travel_need_plan(result.text)
        except LLMGatewayError:
            observability.increment("llm_travel_plan_failures")
            return None
        if not plan:
            observability.increment("llm_travel_plan_invalid")
            return None
        observability.increment("llm_travel_plan_success")
        observability.record_latency("llm_travel_plan_latency_ms", result.latency_ms)
        observability.add_current_step(
            "llm_travel_need_plan",
            {
                "provider": result.provider,
                "model": result.model,
                "latency_ms": round(result.latency_ms, 2),
                "destination": plan.get("destination"),
                "scenario": plan.get("scenario"),
                "slots": [
                    {
                        "role": slot.get("role"),
                        "category": slot.get("category"),
                        "sub_category": slot.get("sub_category"),
                        "search_terms": slot.get("search_terms"),
                    }
                    for slot in plan.get("slots", [])[:5]
                ],
            },
        )
        return plan

    async def _chat(
        self,
        config: LLMConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        response_format_json: bool = False,
    ) -> LLMCallResult:
        endpoint = self._chat_endpoint(config)
        payload = {
            "model": config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format_json and config.provider in {"deepseek", "openai_compatible"}:
            payload["response_format"] = {"type": "json_object"}
        started_at = time.perf_counter()
        if config.provider == "anthropic":
            return await self._chat_anthropic(config, messages, temperature, max_tokens, started_at)
        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds, trust_env=False) as client:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            content = self._message_content(data)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = self._provider_error_detail(exc.response)
            suffix = f"：{detail}" if detail else ""
            raise LLMGatewayError(f"模型接口返回 HTTP {status}{suffix}") from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMGatewayError("模型接口连接或响应解析失败") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMGatewayError("模型返回为空")
        return LLMCallResult(
            text=content.strip(),
            provider=config.provider,
            model=config.model or "",
            latency_ms=(time.perf_counter() - started_at) * 1000,
            usage=data.get("usage") if isinstance(data, dict) else None,
        )

    async def _chat_stream(
        self,
        config: LLMConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        if config.provider == "anthropic":
            async for chunk in self._chat_stream_anthropic(config, messages, temperature, max_tokens):
                yield chunk
            return

        endpoint = self._chat_endpoint(config)
        payload = {
            "model": config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        detail = self._provider_error_detail(response)
                        suffix = f"：{detail}" if detail else ""
                        raise LLMGatewayError(f"模型接口返回 HTTP {response.status_code}{suffix}")
                    async for line in response.aiter_lines():
                        chunk = self._stream_delta_from_line(line)
                        if chunk:
                            yield chunk
        except LLMGatewayError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMGatewayError("模型流式接口连接或响应解析失败") from exc

    async def _chat_stream_anthropic(
        self,
        config: LLMConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        endpoint = self._anthropic_endpoint(config)
        system_parts = [str(message.get("content") or "") for message in messages if message.get("role") == "system"]
        chat_messages = [
            {"role": "assistant" if message.get("role") == "assistant" else "user", "content": str(message.get("content") or "")}
            for message in messages
            if message.get("role") != "system"
        ]
        payload = {
            "model": config.model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_parts:
            payload["system"] = "\n".join(part for part in system_parts if part)
        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers={
                        "x-api-key": config.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        detail = self._provider_error_detail(response)
                        suffix = f"：{detail}" if detail else ""
                        raise LLMGatewayError(f"模型接口返回 HTTP {response.status_code}{suffix}")
                    async for line in response.aiter_lines():
                        chunk = self._anthropic_stream_delta_from_line(line)
                        if chunk:
                            yield chunk
        except LLMGatewayError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMGatewayError("模型流式接口连接或响应解析失败") from exc

    async def _chat_anthropic(
        self,
        config: LLMConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        started_at: float,
    ) -> LLMCallResult:
        endpoint = self._anthropic_endpoint(config)
        system_parts = [str(message.get("content") or "") for message in messages if message.get("role") == "system"]
        chat_messages = [
            {"role": "assistant" if message.get("role") == "assistant" else "user", "content": str(message.get("content") or "")}
            for message in messages
            if message.get("role") != "system"
        ]
        payload = {
            "model": config.model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n".join(part for part in system_parts if part)
        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds, trust_env=False) as client:
                response = await client.post(
                    endpoint,
                    headers={
                        "x-api-key": config.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            content_blocks = data.get("content") if isinstance(data, dict) else None
            text = ""
            if isinstance(content_blocks, list):
                text = "".join(str(block.get("text") or "") for block in content_blocks if isinstance(block, dict) and block.get("type") == "text")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = self._provider_error_detail(exc.response)
            suffix = f"：{detail}" if detail else ""
            raise LLMGatewayError(f"模型接口返回 HTTP {status}{suffix}") from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise LLMGatewayError("模型接口连接或响应解析失败") from exc
        if not text.strip():
            raise LLMGatewayError("模型返回为空")
        return LLMCallResult(
            text=text.strip(),
            provider=config.provider,
            model=config.model or "",
            latency_ms=(time.perf_counter() - started_at) * 1000,
            usage=data.get("usage") if isinstance(data, dict) else None,
        )

    def _config_for_session(self, session_id: str) -> LLMConfig:
        return self._session_configs.get(session_id) or self.default_config

    def _config_from_request(self, request: LLMConfigRequest) -> LLMConfig:
        return self._normalize_config(
            provider=request.provider,
            model=request.model,
            api_key=request.api_key or "",
            base_url=request.base_url,
            temperature=request.temperature,
            source="runtime",
        )

    def _config_from_test_request(self, request: LLMTestRequest) -> LLMConfig:
        base = self._config_for_session(request.session_id)
        if request.provider or request.api_key or request.model or request.base_url:
            return self._normalize_config(
                provider=request.provider or base.provider,
                model=request.model or base.model,
                api_key=request.api_key or base.api_key,
                base_url=request.base_url or base.base_url,
                temperature=request.temperature,
                source="test",
            )
        return replace(base, temperature=request.temperature)

    def _normalize_config(
        self,
        provider: str,
        model: str | None,
        api_key: str,
        base_url: str | None,
        temperature: float,
        source: str,
    ) -> LLMConfig:
        normalized_provider = provider.lower()
        if normalized_provider == "deepseek":
            model = model or DEEPSEEK_MODEL
            base_url = base_url or DEEPSEEK_BASE_URL
        elif normalized_provider == "ark":
            model = model or ARK_MODEL
            base_url = base_url or ARK_BASE_URL
            api_key = api_key or ARK_API_KEY
        elif normalized_provider == "openai_compatible":
            model = model or "deepseek-chat"
        elif normalized_provider == "anthropic":
            model = model or ANTHROPIC_MODEL
            base_url = base_url or ANTHROPIC_BASE_URL
        elif normalized_provider == "disabled":
            model = None
            base_url = None
            api_key = ""
        else:
            raise ValueError("Unsupported LLM provider")
        return LLMConfig(
            provider=normalized_provider,
            model=model,
            api_key=self._sanitize_api_key(api_key),
            base_url=base_url.rstrip("/") if base_url else None,
            temperature=temperature,
            source=source,
        )

    def _chat_endpoint(self, config: LLMConfig) -> str:
        if not config.base_url:
            raise LLMGatewayError("缺少模型 Base URL")
        if config.base_url.endswith("/chat/completions"):
            return config.base_url
        return f"{config.base_url.rstrip('/')}/chat/completions"

    def _anthropic_endpoint(self, config: LLMConfig) -> str:
        if not config.base_url:
            raise LLMGatewayError("缺少模型 Base URL")
        if config.base_url.endswith("/messages"):
            return config.base_url
        return f"{config.base_url.rstrip('/')}/messages"

    def _safe_base_url(self, base_url: str | None) -> str | None:
        return base_url.rstrip("/") if base_url else None

    def _key_hint(self, api_key: str) -> str | None:
        if not api_key:
            return None
        if len(api_key) <= 8:
            return "***"
        return f"{api_key[:3]}...{api_key[-4:]}"

    def _sanitize_api_key(self, api_key: str) -> str:
        compact = re.sub(r"[\s\u200b\u200c\u200d\ufeff\u2060]+", "", api_key or "")
        match = re.search(r"sk-[A-Za-z0-9_-]+", compact)
        if match:
            return match.group(0)
        return compact.strip()

    def _provider_error_detail(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                detail = error.get("message") or error.get("code") or error.get("type")
            else:
                detail = payload.get("message") or payload.get("detail") or error
        else:
            detail = payload
        text = str(detail or "").strip()
        text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
        return text[:160]

    def _message_content(self, data: dict) -> str:
        message = data["choices"][0]["message"]
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        reasoning_content = message.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            return reasoning_content
        return content

    def _stream_delta_from_line(self, line: str) -> str | None:
        line = line.strip()
        if not line or not line.startswith("data:"):
            return None
        payload = line.removeprefix("data:").strip()
        if payload == "[DONE]":
            return None
        data = json.loads(payload)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        choice = choices[0]
        if not isinstance(choice, dict):
            return None
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str) and content:
                return content
            reasoning_content = delta.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content:
                return reasoning_content
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content:
                return content
        return None

    def _anthropic_stream_delta_from_line(self, line: str) -> str | None:
        line = line.strip()
        if not line or not line.startswith("data:"):
            return None
        payload = line.removeprefix("data:").strip()
        data = json.loads(payload)
        if data.get("type") != "content_block_delta":
            return None
        delta = data.get("delta")
        if not isinstance(delta, dict):
            return None
        text = delta.get("text")
        return text if isinstance(text, str) and text else None

    def _parse_travel_need_plan(self, text: str) -> dict | None:
        payload = self._json_object_from_text(text)
        if not isinstance(payload, dict):
            return None
        allowed = {
            ("美妆护肤", "防晒"),
            ("美妆护肤", "面霜"),
            ("美妆护肤", "精华"),
            ("服饰运动", None),
            ("服饰运动", "帽子"),
            ("服饰运动", "背包"),
            ("服饰运动", "徒步鞋"),
            ("服饰运动", "速干T恤"),
            ("服饰运动", "运动服饰"),
            ("服饰运动", "运动装备"),
            ("服饰运动", "运动鞋"),
            ("数码电子", "充电宝"),
            ("数码电子", "充电设备"),
            ("食品饮料", None),
            ("食品饮料", "功能饮料"),
            ("食品饮料", "咖啡"),
            ("食品饮料", "坚果/零食"),
            ("食品饮料", "方便食品"),
        }
        slots = []
        raw_slots = payload.get("slots")
        if not isinstance(raw_slots, list):
            return None
        for raw in raw_slots:
            if not isinstance(raw, dict):
                continue
            category, sub_category = self._normalize_travel_slot_category(raw)
            if (category, sub_category) not in allowed:
                continue
            search_terms_raw = raw.get("search_terms")
            if isinstance(search_terms_raw, list):
                search_terms = " ".join(str(term) for term in search_terms_raw if term)
            else:
                search_terms = str(search_terms_raw or "").strip()
            role = str(raw.get("role") or "").strip()
            reason = str(raw.get("reason") or "").strip()
            if not search_terms or not role:
                continue
            slots.append(
                {
                    "role": role[:24],
                    "category": category,
                    "sub_category": sub_category,
                    "search_terms": search_terms[:80],
                    "reason": reason[:80],
                }
            )
            if len(slots) >= 5:
                break
        if len(slots) < 3:
            return None
        return {
            "destination": str(payload.get("destination") or "").strip()[:24],
            "scenario": str(payload.get("scenario") or "").strip()[:32],
            "intro_focus": str(payload.get("intro_focus") or "").strip()[:80],
            "slots": slots,
        }

    def _normalize_travel_slot_category(self, raw: dict) -> tuple[str, str | None]:
        category_text = str(raw.get("category") or "").strip()
        sub_category_raw = raw.get("sub_category")
        sub_category_text = str(sub_category_raw).strip() if sub_category_raw not in {None, "", "null"} else ""
        combined = f"{category_text} {sub_category_text} {raw.get('role', '')} {raw.get('search_terms', '')}"

        category = category_text.split("/")[0].strip()
        if "美妆护肤" in combined:
            if any(term in combined for term in ("面霜", "保湿", "修护", "屏障", "干燥")):
                return "美妆护肤", "面霜"
            if any(term in combined for term in ("精华", "维稳", "抗氧", "修复")):
                return "美妆护肤", "精华"
            return "美妆护肤", "防晒"
        if "服饰运动" in combined:
            clothing_subcategories = ["帽子", "背包", "徒步鞋", "速干T恤", "运动服饰", "运动装备", "运动鞋"]
            for sub_category in clothing_subcategories:
                if sub_category in combined:
                    return "服饰运动", sub_category
            if any(term in combined for term in ("遮阳", "鸭舌帽")):
                return "服饰运动", "帽子"
            if any(term in combined for term in ("通勤包", "双肩包", "收纳")):
                return "服饰运动", "背包"
            if any(term in combined for term in ("登山", "防滑", "抓地")):
                return "服饰运动", "徒步鞋"
            if any(term in combined for term in ("速干", "短袖", "t恤", "T恤")):
                return "服饰运动", "速干T恤"
            if any(term in combined for term in ("保暖", "thermal", "防晒衣", "衣物")):
                return "服饰运动", "运动服饰"
            if any(term in combined for term in ("收纳袋", "防水袋", "装备")):
                return "服饰运动", "运动装备"
            if "鞋" in combined:
                return "服饰运动", "运动鞋"
            return "服饰运动", None
        if "数码电子" in combined:
            return "数码电子", "充电设备"
        if "食品饮料" in combined:
            food_text = f"{sub_category_text} {raw.get('role', '')} {raw.get('search_terms', '')} {raw.get('reason', '')}"
            if any(term in combined for term in ("咖啡", "提神", "热饮")):
                return "食品饮料", "咖啡"
            if any(term in food_text for term in ("坚果", "零食", "补能")):
                return "食品饮料", "坚果/零食"
            if any(term in food_text for term in ("方便面", "速食", "方便食品")):
                return "食品饮料", "方便食品"
            if any(term in food_text for term in ("功能饮料", "维生素", "补水", "饮料")):
                return "食品饮料", "功能饮料"
            return "食品饮料", None
        if category in {"美妆护肤", "服饰运动", "数码电子", "食品饮料"}:
            if category == "美妆护肤":
                return category, "防晒"
            if category == "数码电子":
                return category, "充电设备"
            return category, None
        return category, sub_category_text or None

    def _json_object_from_text(self, text: str) -> dict | None:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.S)
            if not match:
                return None
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return payload if isinstance(payload, dict) else None

    def _system_prompt(self) -> str:
        return (
            "你是智购罗盘 CartCompass 电商智能导购。只允许基于用户消息和 products 数组里的商品事实回答。"
            "严禁编造不存在的商品、价格、库存、优惠券、折扣、包邮、销量或官方承诺。"
            "回复必须简洁自然，先说明信息来自商品库，再给出 2-3 个推荐理由。"
            "如果用户有排除条件，要明确说明已经避开对应条件。"
            "不要输出 Markdown 表格，不要输出 JSON。"
        )

    def _product_fact(self, product: Product) -> dict:
        return {
            "product_id": product.product_id,
            "title": product.title,
            "brand": product.brand,
            "category": product.category,
            "sub_category": product.sub_category,
            "base_price": product.base_price,
            "highlights": product.highlights[:3],
            "reason": product.reason,
            "sku_prices": [sku.price for sku in product.skus],
        }


class LLMGatewayError(Exception):
    pass

"""兼容 OpenAI Chat Completions 协议的 LLM 客户端。

适用于 OpenAI、DeepSeek、通义千问兼容模式、vLLM、Ollama 等提供
``POST {base_url}/chat/completions`` 的服务。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from agentos.core.exceptions import ConfigurationError, LLMProviderError, LLMTimeoutError
from agentos.core.logging import get_logger
from agentos.llm.base import (
    CompletionOptions,
    LLMClient,
    LLMMessage,
    LLMResponse,
    StreamChunk,
    TokenUsage,
    ToolCall,
)

logger = get_logger(__name__)

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def _parse_tool_calls(raw_calls: Any) -> list[ToolCall] | None:
    """把提供方返回的 ``tool_calls`` 归一化为内部模型。

    对字段缺失或格式异常保持宽容：跳过无法识别的条目，
    避免个别脏数据导致整个响应解析失败。
    """
    if not isinstance(raw_calls, list) or not raw_calls:
        return None

    calls: list[ToolCall] = []
    for index, item in enumerate(raw_calls):
        if not isinstance(item, dict):
            continue
        function = item.get("function") or {}
        name = function.get("name")
        if not name:
            continue
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {}, ensure_ascii=False)
        calls.append(
            ToolCall(
                id=str(item.get("id") or f"call_{index}"),
                name=str(name),
                arguments=arguments,
            )
        )
    return calls or None


class OpenAICompatibleLLMClient(LLMClient):
    """基于 HTTP 的 OpenAI 兼容客户端。"""

    provider = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        default_temperature: float | None = 0.0,
        default_max_tokens: int | None = None,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url:
            raise ConfigurationError("llm.base_url must not be empty")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_retries = max(0, max_retries)
        self._default_temperature = default_temperature
        self._default_max_tokens = default_max_tokens
        self._retry_backoff_seconds = retry_backoff_seconds

        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        self._headers = headers

        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_seconds,
        )

    @property
    def model(self) -> str:
        return self._model

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        payload = self._build_payload(messages, options)
        logger.debug("llm request", extra={"extra_fields": {"payload": payload}})

        for attempt in range(self._max_retries + 1):
            is_last_attempt = attempt >= self._max_retries
            try:
                response = await self._client.post(
                    "/chat/completions", json=payload, headers=self._headers
                )
            except httpx.TimeoutException as exc:
                if is_last_attempt:
                    raise LLMTimeoutError(
                        f"LLM request timed out after {attempt + 1} attempt(s)",
                        details={"base_url": self._base_url, "model": self._model},
                    ) from exc
                await self._sleep_before_retry(attempt, reason="timeout")
                continue
            except httpx.HTTPError as exc:
                if is_last_attempt:
                    raise LLMProviderError(
                        f"LLM request failed: {exc}",
                        details={"base_url": self._base_url, "model": self._model},
                    ) from exc
                await self._sleep_before_retry(attempt, reason=type(exc).__name__)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES and not is_last_attempt:
                await self._sleep_before_retry(
                    attempt, reason=f"http_{response.status_code}"
                )
                continue

            if response.status_code >= 400:
                raise LLMProviderError(
                    f"LLM provider returned HTTP {response.status_code}",
                    details={
                        "status_code": response.status_code,
                        "body": response.text[:500],
                        "model": self._model,
                    },
                )

            return self._parse_response(response)

        raise LLMProviderError("LLM request failed: retries exhausted")

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """流式补全（OpenAI SSE 协议）。

        ``tool_calls`` 在流式响应里是分片下发的，这里按 ``index`` 聚合，
        在流的末尾一次性产出完整的工具调用。

        注意：流式请求**不做重试** —— 一旦开始接收数据，重放会导致内容重复。
        """
        payload = self._build_payload(messages, options)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

        buffers: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        usage: TokenUsage | None = None

        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload, headers=self._headers
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise LLMProviderError(
                        f"LLM provider returned HTTP {response.status_code}",
                        details={
                            "status_code": response.status_code,
                            "body": body[:500],
                            "model": self._model,
                        },
                    )

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue

                    raw_usage = event.get("usage")
                    if raw_usage:
                        usage = TokenUsage(
                            prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
                            completion_tokens=int(raw_usage.get("completion_tokens") or 0),
                            total_tokens=int(raw_usage.get("total_tokens") or 0),
                        )

                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0] or {}
                    if choice.get("finish_reason"):
                        finish_reason = str(choice["finish_reason"])
                    delta = choice.get("delta") or {}

                    text = delta.get("content")
                    if text:
                        yield StreamChunk(delta=str(text))

                    for item in delta.get("tool_calls") or []:
                        index = int(item.get("index") or 0)
                        buffer = buffers.setdefault(
                            index, {"id": "", "name": "", "arguments": ""}
                        )
                        if item.get("id"):
                            buffer["id"] = str(item["id"])
                        function = item.get("function") or {}
                        if function.get("name"):
                            buffer["name"] += str(function["name"])
                        if function.get("arguments"):
                            buffer["arguments"] += str(function["arguments"])
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                "LLM stream timed out",
                details={"base_url": self._base_url, "model": self._model},
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                f"LLM stream failed: {exc}",
                details={"base_url": self._base_url, "model": self._model},
            ) from exc

        calls: list[ToolCall] = []
        for index in sorted(buffers):
            buffer = buffers[index]
            if not buffer["name"]:
                continue
            calls.append(
                ToolCall(
                    id=buffer["id"] or f"call_{index}",
                    name=buffer["name"],
                    arguments=buffer["arguments"] or "{}",
                )
            )

        yield StreamChunk(
            finish_reason=finish_reason, usage=usage, tool_calls=calls or None
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _build_payload(
        self, messages: Sequence[LLMMessage], options: CompletionOptions | None
    ) -> dict[str, Any]:
        resolved_model = (options.model if options else None) or self._model
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [message.to_provider_payload() for message in messages],
        }

        temperature = options.temperature if options else None
        if temperature is None:
            temperature = self._default_temperature
        if temperature is not None:
            payload["temperature"] = temperature

        max_tokens = (options.max_tokens if options else None) or self._default_max_tokens
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if options and options.tools:
            payload["tools"] = [tool.to_provider_payload() for tool in options.tools]

        if options and options.extra:
            payload.update(options.extra)
        return payload

    async def _sleep_before_retry(self, attempt: int, *, reason: str) -> None:
        delay = self._retry_backoff_seconds * (2**attempt)
        logger.warning(
            "llm request retry",
            extra={
                "extra_fields": {
                    "attempt": attempt + 1,
                    "delay_seconds": delay,
                    "reason": reason,
                }
            },
        )
        if delay > 0:
            await asyncio.sleep(delay)

    def _parse_response(self, response: httpx.Response) -> LLMResponse:
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise LLMProviderError(
                "LLM provider returned a non-JSON response",
                details={"body": response.text[:500]},
            ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMProviderError(
                "LLM provider returned no choices",
                details={"body": str(data)[:500]},
            )

        first_choice = choices[0] or {}
        message = first_choice.get("message") or {}
        usage_raw = data.get("usage") or {}
        usage = TokenUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
            total_tokens=int(usage_raw.get("total_tokens") or 0),
        )
        result = LLMResponse(
            content=message.get("content") or "",
            model=data.get("model") or self._model,
            finish_reason=first_choice.get("finish_reason"),
            usage=usage,
            tool_calls=_parse_tool_calls(message.get("tool_calls")),
            raw=data,
        )
        logger.debug(
            "llm response",
            extra={
                "extra_fields": {
                    "model": result.model,
                    "finish_reason": result.finish_reason,
                    "usage": usage.model_dump(),
                }
            },
        )
        return result
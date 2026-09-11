"""LLM 客户端与工厂测试。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agentos.core.config import LLMSettings
from agentos.core.exceptions import ConfigurationError, LLMProviderError, LLMTimeoutError
from agentos.llm import (
    CompletionOptions,
    EchoLLMClient,
    LLMMessage,
    OpenAICompatibleLLMClient,
    ToolCall,
    ToolSpec,
    available_providers,
    create_llm_client,
)


def _mock_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://llm.test/v1"
    )


def _completion_payload(content: str = "hi") -> dict[str, Any]:
    return {
        "model": "test-model",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


def _tool_call_payload(
    name: str = "get_weather", arguments: str = '{"city": "上海"}'
) -> dict[str, Any]:
    return {
        "model": "test-model",
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


async def test_echo_client_is_deterministic() -> None:
    client = EchoLLMClient()
    messages = [LLMMessage.system("be nice"), LLMMessage.user("你好 AgentOS")]

    first = await client.complete(messages)
    second = await client.complete(messages)

    assert first.content == second.content == "Echo: 你好 AgentOS"
    assert first.finish_reason == "stop"
    assert first.usage is not None
    assert first.usage.total_tokens > 0


def test_factory_resolves_registered_providers() -> None:
    assert isinstance(create_llm_client(LLMSettings(provider="echo")), EchoLLMClient)
    assert isinstance(
        create_llm_client(LLMSettings(provider="openai")), OpenAICompatibleLLMClient
    )
    assert "echo" in available_providers()


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        create_llm_client(LLMSettings(provider="not-exist"))

    assert excinfo.value.details["available_providers"]


def test_openai_compatible_requires_base_url() -> None:
    with pytest.raises(ConfigurationError):
        OpenAICompatibleLLMClient(base_url="")


async def test_openai_compatible_builds_request_and_parses_response() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion_payload("hi"))

    async with _mock_client(handler) as http_client:
        client = OpenAICompatibleLLMClient(
            base_url="https://llm.test/v1",
            model="test-model",
            api_key="sk-test",
            client=http_client,
            retry_backoff_seconds=0,
        )

        response = await client.complete(
            [LLMMessage.system("sys"), LLMMessage.user("hello")],
            options=CompletionOptions(temperature=0.2, max_tokens=16),
        )

        assert response.content == "hi"
        assert response.usage is not None
        assert response.usage.total_tokens == 5
        # 外部注入的 httpx 客户端由调用方管理，客户端不应关闭它
        assert http_client.is_closed is False

    assert captured["url"] == "https://llm.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-test"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert captured["body"]["temperature"] == 0.2
    assert captured["body"]["max_tokens"] == 16


async def test_openai_compatible_retries_retryable_status() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json=_completion_payload("recovered"))

    async with _mock_client(handler) as http_client:
        client = OpenAICompatibleLLMClient(
            base_url="https://llm.test/v1",
            client=http_client,
            max_retries=2,
            retry_backoff_seconds=0,
        )

        response = await client.complete([LLMMessage.user("hi")])

    assert len(attempts) == 2
    assert response.content == "recovered"


async def test_openai_compatible_raises_on_client_error_without_retry() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401, json={"error": "bad key"})

    async with _mock_client(handler) as http_client:
        client = OpenAICompatibleLLMClient(
            base_url="https://llm.test/v1",
            client=http_client,
            max_retries=2,
            retry_backoff_seconds=0,
        )

        with pytest.raises(LLMProviderError) as excinfo:
            await client.complete([LLMMessage.user("hi")])

    assert len(attempts) == 1
    assert excinfo.value.details["status_code"] == 401


async def test_openai_compatible_maps_timeout_to_llm_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=request)

    async with _mock_client(handler) as http_client:
        client = OpenAICompatibleLLMClient(
            base_url="https://llm.test/v1",
            client=http_client,
            max_retries=1,
            retry_backoff_seconds=0,
        )

        with pytest.raises(LLMTimeoutError):
            await client.complete([LLMMessage.user("hi")])


async def test_openai_compatible_rejects_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "test-model", "choices": []})

    async with _mock_client(handler) as http_client:
        client = OpenAICompatibleLLMClient(
            base_url="https://llm.test/v1", client=http_client, retry_backoff_seconds=0
        )

        with pytest.raises(LLMProviderError):
            await client.complete([LLMMessage.user("hi")])

async def test_openai_compatible_sends_tools_and_parses_tool_calls() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_tool_call_payload())

    async with _mock_client(handler) as http_client:
        client = OpenAICompatibleLLMClient(
            base_url="https://llm.test/v1", client=http_client, retry_backoff_seconds=0
        )

        response = await client.complete(
            [LLMMessage.user("上海天气怎么样")],
            options=CompletionOptions(
                tools=[ToolSpec(name="get_weather", description="查询天气")]
            ),
        )

    assert captured["body"]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查询天气",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert response.has_tool_calls is True
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls is not None
    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].name == "get_weather"
    assert json.loads(response.tool_calls[0].arguments) == {"city": "上海"}


async def test_openai_compatible_omits_tools_when_not_configured() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion_payload())

    async with _mock_client(handler) as http_client:
        client = OpenAICompatibleLLMClient(
            base_url="https://llm.test/v1", client=http_client, retry_backoff_seconds=0
        )

        await client.complete([LLMMessage.user("hi")])

    assert "tools" not in captured["body"]


async def test_openai_compatible_sends_back_tool_messages() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion_payload("ok"))

    async with _mock_client(handler) as http_client:
        client = OpenAICompatibleLLMClient(
            base_url="https://llm.test/v1", client=http_client, retry_backoff_seconds=0
        )

        await client.complete(
            [
                LLMMessage.user("6*7 等于多少"),
                LLMMessage.assistant(
                    "",
                    tool_calls=[
                        ToolCall(id="call_1", name="calculate", arguments='{"expression": "6*7"}')
                    ],
                ),
                LLMMessage.tool("6*7 = 42", tool_call_id="call_1", name="calculate"),
            ]
        )

    messages = captured["body"]["messages"]
    assert messages[1]["tool_calls"][0]["function"]["name"] == "calculate"
    assert messages[1]["tool_calls"][0]["id"] == "call_1"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_1"
    assert messages[2]["name"] == "calculate"


async def test_openai_compatible_tolerates_malformed_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {
                        "message": {
                            "content": "hi",
                            "tool_calls": [{"bad": "entry"}, "junk"],
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async with _mock_client(handler) as http_client:
        client = OpenAICompatibleLLMClient(
            base_url="https://llm.test/v1", client=http_client, retry_backoff_seconds=0
        )

        response = await client.complete([LLMMessage.user("hi")])

    assert response.content == "hi"
    assert response.tool_calls is None
    assert response.has_tool_calls is False

"""LLM 客户端抽象层。

上层（Agent Runtime）只依赖本模块定义的接口与数据模型，
具体提供方（OpenAI 兼容接口、本地模型、测试替身）通过 :mod:`agentos.llm.factory` 注入。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal, Self

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class ToolSpec(BaseModel):
    """暴露给模型的工具声明（JSON Schema 形式）。

    Runtime 层的工具实现通过 ``Tool.spec()`` 转换成本模型，
    LLM 层再按各提供方协议序列化，保证工具定义与具体协议解耦。
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    def to_provider_payload(self) -> dict[str, Any]:
        """转换为 OpenAI Chat Completions 风格的 ``tools`` 元素。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


class ToolCall(BaseModel):
    """模型发起的一次工具调用请求。

    ``arguments`` 保持提供方原始的 JSON 字符串形式，
    由 Runtime 层解析并按工具声明的 Schema 校验，避免在协议层丢失细节。
    """

    id: str
    name: str
    arguments: str = "{}"

    def to_provider_payload(self) -> dict[str, Any]:
        """转换为 OpenAI Chat Completions 风格的 ``tool_calls`` 元素。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


class LLMMessage(BaseModel):
    """发送给模型的一条消息（与协议无关的内部表示）。"""

    role: Role
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None

    @classmethod
    def system(cls, content: str) -> Self:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> Self:
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str, *, tool_calls: list[ToolCall] | None = None) -> Self:
        return cls(role="assistant", content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, content: str, *, tool_call_id: str, name: str | None = None) -> Self:
        return cls(role="tool", content=content, tool_call_id=tool_call_id, name=name)

    def to_provider_payload(self) -> dict[str, Any]:
        """转换为 OpenAI Chat Completions 风格的消息体。"""
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name is not None:
            payload["name"] = self.name
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            payload["tool_calls"] = [call.to_provider_payload() for call in self.tool_calls]
        return payload


class TokenUsage(BaseModel):
    """Token 用量统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class CompletionOptions(BaseModel):
    """单次补全的可选参数，未设置时回落到配置默认值。"""

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[ToolSpec] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """模型返回结果。"""

    content: str
    model: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    tool_calls: list[ToolCall] | None = None
    raw: dict[str, Any] | None = None

    @property
    def has_content(self) -> bool:
        """返回内容是否非空。"""
        return bool(self.content.strip())

    @property
    def has_tool_calls(self) -> bool:
        """返回模型是否发起了工具调用。"""
        return bool(self.tool_calls)


class StreamChunk(BaseModel):
    """流式补全中的一个片段。

    同一个流里可能出现多类片段：

    - 文本增量：``delta`` 非空
    - 结束片段：``finish_reason`` / ``usage`` / ``tool_calls`` 非空
    """

    delta: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    tool_calls: list[ToolCall] | None = None


class LLMClient(ABC):
    """LLM 客户端接口。"""

    provider: str = "base"

    @abstractmethod
    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        """执行一次补全调用。"""

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """流式补全。

        默认实现退化为一次性返回：先产出完整文本，再产出一个结束片段。
        支持流式的提供方应覆写本方法以逐段返回。
        """
        response = await self.complete(messages, options=options)
        if response.content:
            yield StreamChunk(delta=response.content)
        yield StreamChunk(
            finish_reason=response.finish_reason,
            usage=response.usage,
            tool_calls=response.tool_calls,
        )

    async def aclose(self) -> None:
        """释放底层资源，默认无操作。"""
        return None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
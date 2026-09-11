"""LLM 客户端抽象层。

上层（Agent Runtime）只依赖本模块定义的接口与数据模型，
具体提供方（OpenAI 兼容接口、本地模型、测试替身）通过 :mod:`agentos.llm.factory` 注入。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Literal, Self

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class LLMMessage(BaseModel):
    """发送给模型的一条消息（与协议无关的内部表示）。"""

    role: Role
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: str) -> Self:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> Self:
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str) -> Self:
        return cls(role="assistant", content=content)

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
    extra: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """模型返回结果。"""

    content: str
    model: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    raw: dict[str, Any] | None = None

    @property
    def has_content(self) -> bool:
        """返回内容是否非空。"""
        return bool(self.content.strip())


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

    async def aclose(self) -> None:
        """释放底层资源，默认无操作。"""
        return None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
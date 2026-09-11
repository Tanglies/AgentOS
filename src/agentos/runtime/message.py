"""运行时消息模型。

与 LLM 层的 :class:`~agentos.llm.base.LLMMessage` 相比，这里额外携带元数据与时间戳，
在到达模型调用边界时再转换为协议无关的 ``LLMMessage``。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field

from agentos.llm.base import LLMMessage, ToolCall


def utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(UTC)


class MessageRole(StrEnum):
    """消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """会话中的一条消息。"""

    role: MessageRole
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @classmethod
    def system(cls, content: str) -> Self:
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> Self:
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str, *, tool_calls: list[ToolCall] | None = None) -> Self:
        return cls(role=MessageRole.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, content: str, *, tool_call_id: str, name: str | None = None) -> Self:
        return cls(
            role=MessageRole.TOOL, content=content, tool_call_id=tool_call_id, name=name
        )

    def to_llm_message(self) -> LLMMessage:
        """转换为 LLM 层消息。"""
        return LLMMessage(
            role=self.role.value,
            content=self.content,
            name=self.name,
            tool_call_id=self.tool_call_id,
            tool_calls=self.tool_calls,
        )
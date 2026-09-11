"""Agent 定义。

v0.1 的 Agent 由「人设 + 模型参数」构成；工具、记忆与子 Agent 会在后续版本挂载到这里。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from agentos.llm.base import CompletionOptions
from agentos.runtime.message import Message

AGENT_NAME_PATTERN = r"^[A-Za-z0-9_-]+$"


class Agent(BaseModel):
    """一个可执行的 Agent 定义。"""

    name: str = Field(min_length=1, max_length=64, pattern=AGENT_NAME_PATTERN)
    description: str = ""
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_iterations: int | None = Field(default=None, ge=1, le=64)
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def build_messages(
        self, input_text: str, *, history: Sequence[Message] | None = None
    ) -> list[Message]:
        """组装本次运行的消息列表：系统提示词 → 历史消息 → 用户输入。"""
        messages: list[Message] = []
        if self.system_prompt:
            messages.append(Message.system(self.system_prompt))
        if history:
            messages.extend(history)
        messages.append(Message.user(input_text))
        return messages

    def completion_options(self) -> CompletionOptions:
        """把 Agent 级模型参数转换为单次调用选项。"""
        return CompletionOptions(model=self.model, temperature=self.temperature)
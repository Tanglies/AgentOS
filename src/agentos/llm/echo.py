"""本地确定性 LLM 客户端。

不访问任何外部服务，回显最后一条用户消息，用于本地开发、示例与测试。
"""

from __future__ import annotations

from collections.abc import Sequence

from agentos.llm.base import CompletionOptions, LLMClient, LLMMessage, LLMResponse, TokenUsage


class EchoLLMClient(LLMClient):
    """回显式客户端：给定相同输入总是返回相同结果。"""

    provider = "echo"

    def __init__(self, *, model: str = "echo-1", prefix: str = "Echo: ") -> None:
        self._model = model
        self._prefix = prefix

    @property
    def model(self) -> str:
        return self._model

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        message_list = list(messages)
        last_user = next((m for m in reversed(message_list) if m.role == "user"), None)
        content = f"{self._prefix}{last_user.content if last_user else ''}"
        prompt_tokens = sum(len(m.content.split()) for m in message_list)
        completion_tokens = len(content.split())
        return LLMResponse(
            content=content,
            model=options.model if options and options.model else self._model,
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )
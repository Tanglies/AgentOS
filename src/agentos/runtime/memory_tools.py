"""长期记忆工具：让 Agent 自己决定记住什么、何时回忆。

与 :mod:`agentos.runtime.memory` 的短期会话记忆不同，这里的记忆
**跨会话持久保留**，因此只在模型判断「值得长期记住」时才写入。
"""

from __future__ import annotations

from agentos.runtime.long_term_memory import LongTermMemory
from agentos.runtime.tools import Tool, truncate_text


class RememberTool(Tool):
    """把信息写入长期记忆。"""

    name = "remember"
    description = (
        "把一条值得长期保留的信息写入记忆库，供以后的会话检索使用。"
        "适合记住用户偏好、身份、项目约定等稳定事实；"
        "不要记录一次性的临时内容或敏感凭据。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "要记住的内容，用一句完整独立的话描述，例如「用户偏好用中文回答」",
            },
            "scope": {
                "type": "string",
                "enum": ["user", "workspace"],
                "description": "user 仅本人可见，workspace 当前 Workspace 成员共享",
            },
        },
        "required": ["content"],
    }

    def __init__(self, memory: LongTermMemory) -> None:
        self._memory = memory

    async def run(self, content: str, scope: str = "workspace") -> str:
        record = self._memory.remember(content, scope=scope)
        return (
            f"已写入长期记忆（id={record.id}, scope={record.scope.value}）："
            f"{record.content}"
        )


class RecallTool(Tool):
    """从长期记忆中检索。"""

    name = "recall"
    description = (
        "从长期记忆库中检索与查询相关的历史信息。"
        "需要回忆用户偏好、既往结论或项目约定时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词或问题"},
            "scope": {
                "type": "string",
                "enum": ["user", "workspace"],
                "description": "可选；限定只搜索本人或 Workspace 共享记忆",
            },
        },
        "required": ["query"],
    }

    def __init__(self, memory: LongTermMemory) -> None:
        self._memory = memory

    async def run(self, query: str, scope: str | None = None) -> str:
        records = self._memory.recall(query, scope=scope)
        if not records:
            return f"没有找到与「{query}」相关的长期记忆。"

        lines = [f"找到 {len(records)} 条相关记忆："]
        lines.extend(f"- [{record.id}] {record.content}" for record in records)
        return truncate_text("\n".join(lines), 4000)


def create_memory_tools(memory: LongTermMemory) -> list[Tool]:
    """创建长期记忆工具。"""
    return [RememberTool(memory), RecallTool(memory)]
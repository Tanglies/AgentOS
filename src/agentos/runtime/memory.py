"""会话记忆。

当前实现是**进程内短期记忆**：按 ``session_id`` 保存最近若干轮对话，
让 Agent 在多轮交互中记住上下文。进程重启即清空；
持久化存储与长期记忆（向量检索）属于阶段 2 的后续任务。

两个容量约束：

- ``max_messages_per_session``：单个会话只保留最近 N 条消息
- ``max_sessions``：会话总数上限，超出按 LRU 淘汰最久未使用的会话

截断时按**轮次边界**对齐：只保留从一个 ``user`` 消息开始的完整片段，
避免把 ``assistant(tool_calls)`` 与其后的 ``tool`` 结果拆散 —— 那样再发给
OpenAI 兼容接口会因为 tool_calls 缺少对应结果而报错。
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from agentos.core.config import MemorySettings
from agentos.core.context import new_id
from agentos.runtime.message import Message, MessageRole, utcnow


def _trim_turns(messages: list[Message], limit: int) -> list[Message]:
    """保留最近 ``limit`` 条消息，并对齐到完整轮次的起点。"""
    if len(messages) <= limit:
        return list(messages)

    candidate = messages[-limit:]
    for index, message in enumerate(candidate):
        if message.role == MessageRole.USER:
            return candidate[index:]
    return []


class SessionState(BaseModel):
    """一个会话的记忆快照。"""

    session_id: str
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def turn_count(self) -> int:
        """已发生的用户轮次数。"""
        return sum(1 for message in self.messages if message.role == MessageRole.USER)


class MemoryStore:
    """进程内会话记忆，按 ``session_id`` 隔离。"""

    def __init__(self, settings: MemorySettings | None = None) -> None:
        self._settings = settings or MemorySettings()
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()

    @staticmethod
    def new_session_id() -> str:
        """生成一个新的会话 ID。"""
        return new_id("sess_")

    def get(self, session_id: str) -> SessionState | None:
        """返回会话快照，不存在时返回 ``None``。"""
        state = self._sessions.get(session_id)
        if state is not None:
            self._sessions.move_to_end(session_id)
        return state

    def history(self, session_id: str) -> list[Message]:
        """返回可用于组装消息的历史（不含系统提示词）。"""
        state = self.get(session_id)
        return list(state.messages) if state is not None else []

    def append(self, session_id: str, messages: Sequence[Message]) -> SessionState:
        """把本轮新增消息追加到会话，并按容量约束截断。"""
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState(session_id=session_id)
            self._sessions[session_id] = state

        state.messages.extend(messages)
        state.messages = _trim_turns(state.messages, self._settings.max_messages_per_session)
        state.updated_at = utcnow()

        self._sessions.move_to_end(session_id)
        self._evict()
        return state

    def clear(self, session_id: str) -> bool:
        """删除会话，返回是否确实存在。"""
        return self._sessions.pop(session_id, None) is not None

    def list(self) -> list[SessionState]:
        """返回全部会话，最近更新的排在前面。"""
        return list(reversed(self._sessions.values()))

    def _evict(self) -> None:
        """按 LRU 淘汰超出上限的会话。"""
        while len(self._sessions) > self._settings.max_sessions:
            self._sessions.popitem(last=False)

    def __contains__(self, session_id: object) -> bool:
        return isinstance(session_id, str) and session_id in self._sessions

    def __len__(self) -> int:
        return len(self._sessions)
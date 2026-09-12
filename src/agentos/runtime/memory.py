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
from agentos.core.context import get_user_id, get_workspace_id, new_id
from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
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
    workspace_id: int = DEFAULT_WORKSPACE_ID
    user_id: int = DEFAULT_USER_ID
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
        self._sessions: OrderedDict[tuple[int, int, str], SessionState] = OrderedDict()

    @staticmethod
    def _scope(
        workspace_id: int | None = None, user_id: int | None = None
    ) -> tuple[int, int]:
        return (
            workspace_id or get_workspace_id() or DEFAULT_WORKSPACE_ID,
            user_id if user_id is not None else get_user_id() or DEFAULT_USER_ID,
        )

    @classmethod
    def _key(
        cls,
        session_id: str,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> tuple[int, int, str]:
        workspace, user = cls._scope(workspace_id, user_id)
        return workspace, user, session_id

    @staticmethod
    def new_session_id() -> str:
        """生成一个新的会话 ID。"""
        return new_id("sess_")

    def resolve_session_id(self, session_id: str | None) -> str | None:
        """解析实际使用的会话 ID。

        显式传入优先；未传时回退到 ``default_session_id``，
        该配置为空字符串则返回 ``None``（即无状态）。
        """
        if session_id:
            return session_id
        fallback = self._settings.default_session_id.strip()
        return fallback or None

    def get(
        self,
        session_id: str,
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> SessionState | None:
        """返回当前租户的会话快照。"""
        key = self._key(session_id, workspace_id, user_id)
        state = self._sessions.get(key)
        if state is not None:
            self._sessions.move_to_end(key)
        return state

    def history(
        self,
        session_id: str,
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> list[Message]:
        """返回当前租户会话的历史。"""
        state = self.get(session_id, workspace_id=workspace_id, user_id=user_id)
        return list(state.messages) if state is not None else []

    def append(
        self,
        session_id: str,
        messages: Sequence[Message],
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> SessionState:
        """把本轮新增消息追加到当前租户的会话。"""
        scope = self._scope(workspace_id, user_id)
        key = (*scope, session_id)
        state = self._sessions.get(key)
        if state is None:
            state = SessionState(
                session_id=session_id,
                workspace_id=scope[0],
                user_id=scope[1],
            )
            self._sessions[key] = state

        state.messages.extend(messages)
        state.messages = _trim_turns(state.messages, self._settings.max_messages_per_session)
        state.updated_at = utcnow()

        self._sessions.move_to_end(key)
        self._evict()
        return state

    def clear(
        self,
        session_id: str,
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> bool:
        """删除当前租户会话，返回是否确实存在。"""
        return self._sessions.pop(self._key(session_id, workspace_id, user_id), None) is not None

    def list(
        self,
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> list[SessionState]:
        """返回当前租户全部会话，最近更新的排在前面。"""
        scope = self._scope(workspace_id, user_id)
        return [
            state
            for key, state in reversed(self._sessions.items())
            if key[:2] == scope
        ]

    def _evict(self) -> None:
        """按 LRU 淘汰超出上限的会话。"""
        while len(self._sessions) > self._settings.max_sessions:
            self._sessions.popitem(last=False)

    def __contains__(self, session_id: object) -> bool:
        return (
            isinstance(session_id, str)
            and self._key(session_id) in self._sessions
        )

    def __len__(self) -> int:
        scope = self._scope(None, None)
        return sum(1 for key in self._sessions if key[:2] == scope)
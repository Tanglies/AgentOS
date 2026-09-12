"""审计日志。

与普通日志的分工：

| | 普通日志 | 审计日志 |
| --- | --- | --- |
| 读者 | 开发者 | 合规与追责 |
| 内容 | 任意调试信息 | 固定的四要素 |
| 去向 | stdout，会被采集系统滚动 | SQLite，持久可查 |
| 量级 | 大 | 小（只记关键动作） |

固定回答四个问题：

- **谁** ``actor`` —— API Key 指纹，认证关闭时为 ``None``（匿名）
- **什么时候** ``created_at``
- **对什么做了什么** ``action`` + ``target``
- **结果如何** ``status``

设计要点：``trace_id`` / ``run_id`` / ``agent_name`` / ``tool_name`` / ``actor``
**全部自动从 contextvars 取**。调用方只需说明「做了什么、结果如何」，
不必手动传上下文 —— 少传一个字段就少一个漏记的理由。
"""

from __future__ import annotations

from pathlib import Path

from agentos.core.config import AuditSettings
from agentos.core.context import (
    get_actor,
    get_agent_name,
    get_run_id,
    get_tool_name,
    get_trace_id,
)
from agentos.core.database import Database
from agentos.runtime.repositories import (
    AUDIT_SCHEMA,
    AuditEntry,
    AuditRepository,
    AuditStatus,
)

ACTION_AGENT_RUN = "agent.run"
ACTION_TOOL_EXECUTE = "tool.execute"
ACTION_AGENT_REGISTER = "agent.register"
ACTION_AGENT_UNREGISTER = "agent.unregister"

__all__ = [
    "ACTION_AGENT_REGISTER",
    "ACTION_AGENT_RUN",
    "ACTION_AGENT_UNREGISTER",
    "ACTION_TOOL_EXECUTE",
    "AuditEntry",
    "AuditLog",
    "AuditStatus",
]


class AuditLog:
    """审计日志存储。"""

    def __init__(self, settings: AuditSettings | None = None) -> None:
        self._settings = settings or AuditSettings()
        self.path = Path(self._settings.db_path).expanduser()
        self._db = Database(self.path, schema=AUDIT_SCHEMA)
        self._repo = AuditRepository(self._db)

    @property
    def repository(self) -> AuditRepository:
        """底层 Repository，供只读查询直接使用。"""
        return self._repo

    def record(
        self,
        action: str,
        *,
        status: AuditStatus = AuditStatus.SUCCESS,
        target: str | None = None,
        detail: str = "",
    ) -> AuditEntry:
        """写入一条审计记录，上下文里的字段自动带上。"""
        entry = AuditEntry(
            action=action,
            status=status,
            target=target,
            detail=detail[:2000],
            actor=get_actor(),
            trace_id=get_trace_id(),
            run_id=get_run_id(),
            agent_name=get_agent_name(),
            tool_name=get_tool_name(),
        )
        saved = self._repo.add(entry)
        self._repo.prune(self._settings.max_records)
        return saved

    def list(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        run_id: str | None = None,
        status: AuditStatus | None = None,
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """按条件查询审计记录，默认最新在前。"""
        return self._repo.list(
            action=action,
            actor=actor,
            run_id=run_id,
            status=status,
            order=order,
            limit=limit,
            offset=offset,
        )

    def count(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        run_id: str | None = None,
        status: AuditStatus | None = None,
    ) -> int:
        """满足条件的记录总数。"""
        return self._repo.count(
            action=action, actor=actor, run_id=run_id, status=status
        )

    def clear(self) -> int:
        """清空全部记录，返回删除条数。"""
        return self._repo.clear()
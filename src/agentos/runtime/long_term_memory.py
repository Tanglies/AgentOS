"""长期记忆：跨会话持久化的记忆存储与检索。

与 :mod:`agentos.runtime.memory` 的**短期会话记忆**相比：

| 维度 | 短期（memory.py） | 长期（本模块） |
| --- | --- | --- |
| 范围 | 单个 `session_id` | 跨会话共享 |
| 存储 | 进程内存 | SQLite 文件 |
| 生命周期 | 进程重启即丢 | 持久保留 |
| 用途 | 记住当前对话 | 记住用户偏好、事实、结论 |

**检索是关键词匹配，不是语义检索**：把查询切成英文词与中文二元组，
按命中词长度加权排序。这样不需要 embedding 依赖、也不额外调用模型；
代价是同义改写或跨语言查询召回率有限，后续可以替换为向量检索。

数据访问委托给 :class:`~agentos.runtime.repositories.MemoryRepository`，
本模块只负责检索词抽取与对外语义。

.. note::

   ``MemoryRecord`` 从 repositories 重新导出，
   保证既有的 ``from agentos.runtime.long_term_memory import MemoryRecord`` 仍可用。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from agentos.core.config import MemorySettings
from agentos.core.context import get_user_id, get_workspace_id
from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.database.connection import Database
from agentos.runtime.repositories import (
    MEMORIES_SCHEMA,
    MemoryRecord,
    MemoryRepository,
    MemoryScope,
)

MAX_CONTENT_CHARS = 4000

__all__ = [
    "MAX_CONTENT_CHARS",
    "LongTermMemory",
    "MemoryRecord",
    "MemoryScope",
    "extract_terms",
]

_ASCII_WORD_PATTERN = re.compile(r"[A-Za-z0-9_]{2,}")
_CJK_RUN_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


def extract_terms(query: str) -> list[str]:
    """从查询中抽取检索词。

    英文/数字按词切分；中文额外生成二元组 —— 中文没有空格分词，
    而 SQLite 内置 FTS5 的 tokenizer 对中文支持很差（两个字的中文词都召不回），
    所以这里退回到子串匹配，并用二元组提高召回。
    """
    terms: list[str] = []

    for word in _ASCII_WORD_PATTERN.findall(query):
        terms.append(word.lower())

    for run in _CJK_RUN_PATTERN.findall(query):
        if len(run) <= 2:
            terms.append(run)
            continue
        terms.append(run)
        terms.extend(run[index : index + 2] for index in range(len(run) - 1))

    unique: list[str] = []
    for term in terms:
        if len(term) >= 2 and term not in unique:
            unique.append(term)
    return unique


class LongTermMemory:
    """基于 SQLite 的长期记忆存储。"""

    def __init__(self, settings: MemorySettings | None = None) -> None:
        self._settings = settings or MemorySettings()
        self.path = Path(self._settings.long_term_db_path).expanduser()
        self._db = Database(self.path, schema=MEMORIES_SCHEMA)
        self._repo = MemoryRepository(self._db)

    @property
    def auto_recall(self) -> bool:
        """是否在每次运行前自动召回相关记忆。"""
        return self._settings.long_term_auto_recall

    @staticmethod
    def _scope_ids(
        workspace_id: int | None = None, user_id: int | None = None
    ) -> tuple[int, int]:
        return (
            workspace_id or get_workspace_id() or DEFAULT_WORKSPACE_ID,
            user_id if user_id is not None else get_user_id() or DEFAULT_USER_ID,
        )

    def remember(
        self,
        content: str,
        *,
        session_id: str | None = None,
        scope: MemoryScope | str = MemoryScope.WORKSPACE,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> MemoryRecord:
        """写入一条记忆，scope 和租户标识来自上下文。"""
        text = content.strip()[:MAX_CONTENT_CHARS]
        if not text:
            raise ValueError("memory content must not be empty")
        resolved_scope = MemoryScope(scope)
        resolved_workspace, resolved_user = self._scope_ids(workspace_id, user_id)
        return self._repo.add(
            content=text,
            session_id=session_id,
            created_at=datetime.now(UTC),
            workspace_id=resolved_workspace,
            user_id=resolved_user if resolved_scope == MemoryScope.USER else None,
            scope=resolved_scope,
        )

    def recall(
        self,
        query: str,
        *,
        limit: int | None = None,
        scope: MemoryScope | str | None = None,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> list[MemoryRecord]:
        """按关键词和 tenant visibility 召回记忆。"""
        terms = extract_terms(query)
        if not terms:
            return []
        resolved_workspace, resolved_user = self._scope_ids(workspace_id, user_id)
        return self._repo.search(
            terms=terms,
            limit=limit or self._settings.long_term_recall_limit,
            workspace_id=resolved_workspace,
            user_id=resolved_user,
            scope=MemoryScope(scope) if scope is not None else None,
        )

    def list(
        self,
        *,
        limit: int = 50,
        scope: MemoryScope | str | None = None,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> list[MemoryRecord]:
        """按写入时间倒序返回当前 Workspace 可见记忆。"""
        resolved_workspace, resolved_user = self._scope_ids(workspace_id, user_id)
        return self._repo.list(
            limit=limit,
            workspace_id=resolved_workspace,
            user_id=resolved_user,
            scope=MemoryScope(scope) if scope is not None else None,
        )

    def forget(
        self,
        memory_id: int,
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> bool:
        """删除当前租户可见的一条记忆。"""
        resolved_workspace, resolved_user = self._scope_ids(workspace_id, user_id)
        return self._repo.remove(
            memory_id,
            workspace_id=resolved_workspace,
            user_id=resolved_user,
        )

    def clear(
        self, *, workspace_id: int | None = None, user_id: int | None = None
    ) -> int:
        """清空当前租户可见记忆。"""
        resolved_workspace, resolved_user = self._scope_ids(workspace_id, user_id)
        return self._repo.clear(
            workspace_id=resolved_workspace, user_id=resolved_user
        )

    def count(
        self, *, workspace_id: int | None = None, user_id: int | None = None
    ) -> int:
        """返回当前租户可见记忆条数。"""
        resolved_workspace, resolved_user = self._scope_ids(workspace_id, user_id)
        return self._repo.count(
            workspace_id=resolved_workspace, user_id=resolved_user
        )
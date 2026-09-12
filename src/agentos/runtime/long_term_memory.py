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
from agentos.core.database import Database
from agentos.runtime.repositories import (
    MEMORIES_SCHEMA,
    MemoryRecord,
    MemoryRepository,
)

MAX_CONTENT_CHARS = 4000

__all__ = ["MAX_CONTENT_CHARS", "LongTermMemory", "MemoryRecord", "extract_terms"]

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

    def remember(self, content: str, *, session_id: str | None = None) -> MemoryRecord:
        """写入一条记忆，内容按 ``MAX_CONTENT_CHARS`` 截断。"""
        text = content.strip()[:MAX_CONTENT_CHARS]
        if not text:
            raise ValueError("memory content must not be empty")
        return self._repo.add(
            content=text, session_id=session_id, created_at=datetime.now(UTC)
        )

    def recall(self, query: str, *, limit: int | None = None) -> list[MemoryRecord]:
        """按关键词相关性召回记忆，无命中时返回空列表。"""
        terms = extract_terms(query)
        if not terms:
            return []
        return self._repo.search(
            terms=terms, limit=limit or self._settings.long_term_recall_limit
        )

    def list(self, *, limit: int = 50) -> list[MemoryRecord]:
        """按写入时间倒序返回记忆。"""
        return self._repo.list(limit=limit)

    def forget(self, memory_id: int) -> bool:
        """删除一条记忆，返回是否确实存在。"""
        return self._repo.remove(memory_id)

    def clear(self) -> int:
        """清空全部记忆，返回删除条数。"""
        return self._repo.clear()

    def count(self) -> int:
        """返回记忆总条数。"""
        return self._repo.count()
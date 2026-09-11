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

存储位置由 ``MemorySettings.long_term_db_path`` 配置，默认 ``.agentos/memory.db``。
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from agentos.core.config import MemorySettings

MAX_CONTENT_CHARS = 4000

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_WORD_PATTERN = re.compile(r"[A-Za-z0-9_]{2,}")
_CJK_RUN_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
_CJK_TOKEN = re.compile(r"[\u4e00-\u9fff]")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories (created_at DESC);
"""


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


class MemoryRecord(BaseModel):
    """一条长期记忆。"""

    id: int
    content: str
    session_id: str | None = None
    created_at: datetime


class LongTermMemory:
    """基于 SQLite 的长期记忆存储。"""

    def __init__(self, settings: MemorySettings | None = None) -> None:
        self._settings = settings or MemorySettings()
        self.path = Path(self._settings.long_term_db_path).expanduser()
        if self.path.parent != Path(""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def auto_recall(self) -> bool:
        """是否在每次运行前自动召回相关记忆。"""
        return self._settings.long_term_auto_recall

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """打开连接并在退出时关闭。

        注意：``sqlite3`` 的 ``with conn`` 只管理事务提交/回滚，
        并不会关闭连接；必须显式 close，否则会泄漏文件句柄。
        """
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=int(row["id"]),
            content=str(row["content"]),
            session_id=row["session_id"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def remember(self, content: str, *, session_id: str | None = None) -> MemoryRecord:
        """写入一条记忆。

        内容按 ``MAX_CONTENT_CHARS`` 截断，避免单条记忆占满上下文。
        """
        text = content.strip()[:MAX_CONTENT_CHARS]
        if not text:
            raise ValueError("memory content must not be empty")

        created_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO memories (content, session_id, created_at) VALUES (?, ?, ?)",
                (text, session_id, created_at),
            )
            memory_id = int(cursor.lastrowid or 0)

        return MemoryRecord(
            id=memory_id,
            content=text,
            session_id=session_id,
            created_at=datetime.fromisoformat(created_at),
        )

    def recall(self, query: str, *, limit: int | None = None) -> list[MemoryRecord]:
        """按关键词相关性召回记忆，无命中时返回空列表。"""
        terms = extract_terms(query)
        if not terms:
            return []

        resolved_limit = limit or self._settings.long_term_recall_limit
        score_parts = [
            "CASE WHEN lower(content) LIKE ? THEN ? ELSE 0 END" for _ in terms
        ]
        score_expr = " + ".join(score_parts)

        params: list[object] = []
        for term in terms:
            params.append(f"%{term.lower()}%")
            params.append(len(term))
        params.append(resolved_limit)

        sql = (
            "SELECT id, content, session_id, created_at, score FROM ("
            "  SELECT id, content, session_id, created_at,"
            f"  ({score_expr}) AS score FROM memories"
            ") WHERE score > 0 "
            "ORDER BY score DESC, created_at DESC, id DESC LIMIT ?"
        )

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._to_record(row) for row in rows]

    def list(self, *, limit: int = 50) -> list[MemoryRecord]:
        """按写入时间倒序返回记忆。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, content, session_id, created_at FROM memories "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def forget(self, memory_id: int) -> bool:
        """删除一条记忆，返回是否确实存在。"""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0

    def clear(self) -> int:
        """清空全部记忆，返回删除条数。"""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories")
        return max(0, cursor.rowcount)

    def count(self) -> int:
        """返回记忆总条数。"""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM memories").fetchone()
        return int(row["total"]) if row is not None else 0
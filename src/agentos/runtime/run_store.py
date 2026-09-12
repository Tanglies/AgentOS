"""运行记录持久化与历史查询。

每次 Agent 运行结束后把结果落盘到 SQLite，解决「跑完就查不到」的问题 ——
在此之前 ``run_id`` 只存在于日志里，没有任何接口能回看某次运行做了什么。

存储方式与 Agent 注册表一致：

- **结构化字段建列**（agent / session_id / status / created_at / tokens）
  用于过滤与排序
- **完整结果序列化成 JSON** 存 ``payload`` 列，避免每次给 ``RunResult``
  加字段都改表结构

记录保留最近 ``max_records`` 条，超出后按时间淘汰最旧的，
避免长期运行把磁盘占满。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from agentos.core.config import RunStoreSettings
from agentos.core.exceptions import NotFoundError
from agentos.runtime.message import Message

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注，避免与 runtime 循环导入
    from agentos.runtime.runtime import RunResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    session_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    duration_ms REAL NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs (agent);
CREATE INDEX IF NOT EXISTS idx_runs_session ON runs (session_id);
"""

MAX_INPUT_CHARS = 4000


class RunStatus(StrEnum):
    """运行状态。"""

    COMPLETED = "completed"
    FAILED = "failed"


class RunRecord(BaseModel):
    """一次运行的记录。"""

    run_id: str
    agent: str
    session_id: str | None = None
    status: RunStatus = RunStatus.COMPLETED
    input: str = ""
    output: str = ""
    error: str | None = None
    iterations: int = 0
    duration_ms: float = 0.0
    tool_call_count: int = 0
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    messages: list[Message] = Field(default_factory=list)


class RunStore:
    """基于 SQLite 的运行记录存储。"""

    def __init__(self, settings: RunStoreSettings | None = None) -> None:
        self._settings = settings or RunStoreSettings()
        self.path = Path(self._settings.db_path).expanduser()
        if self.path.parent != Path(""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """打开连接并在退出时关闭（``with conn`` 只管理事务，不关连接）。"""
        # 目录/文件可能被外部删掉（例如手工清理 .agentos/），
        # 这里每次连接都确保目录存在；文件是新建的就重建表结构。
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.path.exists()

        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                if is_new:
                    conn.executescript(_SCHEMA)
                yield conn
        finally:
            conn.close()

    # --- 写入 ---------------------------------------------------------

    def record(self, result: RunResult, *, input_text: str = "") -> RunRecord:
        """记录一次成功的运行。"""
        usage = result.usage
        record = RunRecord(
            run_id=result.run_id,
            agent=result.agent,
            session_id=result.session_id,
            status=RunStatus.COMPLETED,
            input=input_text[:MAX_INPUT_CHARS],
            output=result.output,
            iterations=result.iterations,
            duration_ms=result.duration_ms,
            tool_call_count=result.tool_call_count,
            finish_reason=result.finish_reason,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            messages=list(result.messages),
        )
        self._insert(record)
        return record

    def record_failure(
        self,
        *,
        run_id: str,
        agent: str,
        input_text: str,
        error: str,
        session_id: str | None = None,
        duration_ms: float = 0.0,
    ) -> RunRecord:
        """记录一次失败的运行 —— 失败同样值得留痕，便于排查。"""
        record = RunRecord(
            run_id=run_id,
            agent=agent,
            session_id=session_id,
            status=RunStatus.FAILED,
            input=input_text[:MAX_INPUT_CHARS],
            error=error,
            duration_ms=duration_ms,
        )
        self._insert(record)
        return record

    def _insert(self, record: RunRecord) -> None:
        payload = record.model_dump_json()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs "
                "(run_id, agent, session_id, status, created_at, duration_ms, "
                " total_tokens, tool_call_count, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.run_id,
                    record.agent,
                    record.session_id,
                    record.status.value,
                    record.created_at.isoformat(),
                    record.duration_ms,
                    record.total_tokens,
                    record.tool_call_count,
                    payload,
                ),
            )
        self._prune()

    def _prune(self) -> None:
        """只保留最近 ``max_records`` 条。"""
        limit = self._settings.max_records
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM runs WHERE run_id IN ("
                "  SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?"
                ")",
                (limit,),
            )

    # --- 查询 ---------------------------------------------------------

    def get(self, run_id: str) -> RunRecord:
        """按 run_id 取一条记录。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"run not found: {run_id}", details={"run_id": run_id})
        return RunRecord.model_validate(json.loads(str(row["payload"])))

    def list(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RunRecord]:
        """按条件查询历史运行，最新在前。

        只返回摘要字段（不含 messages），避免列表接口把上下文撑爆。
        """
        where, params = self._build_filter(agent=agent, session_id=session_id, status=status)
        sql = (
            "SELECT payload FROM runs "
            f"{where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
        )
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, limit, offset)).fetchall()

        records = [RunRecord.model_validate(json.loads(str(row["payload"]))) for row in rows]
        return [record.model_copy(update={"messages": []}) for record in records]

    def count(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        status: RunStatus | None = None,
    ) -> int:
        """满足条件的记录总数（分页用）。"""
        where, params = self._build_filter(agent=agent, session_id=session_id, status=status)
        with self._connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS total FROM runs {where}", params).fetchone()
        return int(row["total"]) if row is not None else 0

    @staticmethod
    def _build_filter(
        *,
        agent: str | None,
        session_id: str | None,
        status: RunStatus | None,
    ) -> tuple[str, tuple[object, ...]]:
        clauses: list[str] = []
        params: list[object] = []
        if agent:
            clauses.append("agent = ?")
            params.append(agent)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)

    def clear(self) -> int:
        """清空全部记录，返回删除条数。"""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM runs")
        return max(0, cursor.rowcount)
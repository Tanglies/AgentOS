"""数据访问层（Repository）。

把 SQL 语句与「行 ↔ 模型」的转换从业务对象里搬出来：
``RunStore`` / ``SQLiteAgentRegistry`` / ``LongTermMemory`` 只负责编排与语义，
不再直接拼 SQL。

每个 Repository 接收一个 :class:`~agentos.core.database.Database`，
只关心自己那张表，互相不引用。

实体模型（``RunRecord`` / ``MemoryRecord``）也定义在这里，
由各存储模块重新导出，保证既有导入路径不变。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agentos.core.database import Database
from agentos.runtime.agent import Agent
from agentos.runtime.message import Message

AGENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

RUNS_SCHEMA = """
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

API_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    permissions TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys (key_hash);
"""

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    target TEXT,
    actor TEXT,
    trace_id TEXT,
    run_id TEXT,
    agent_name TEXT,
    tool_name TEXT,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs (action);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs (actor);
CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_logs (run_id);
"""

MEMORIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories (created_at DESC);
"""


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


class ApiKeyRecord(BaseModel):
    """一条 API Key 记录。

    **只保存 hash，不保存明文**。明文只在创建时返回一次，
    之后无法从数据库还原 —— 丢失只能重新签发。
    """

    id: int | None = None
    key_hash: str
    name: str
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None


class AuditStatus(StrEnum):
    """审计结果。"""

    SUCCESS = "success"
    FAILURE = "failure"


class AuditEntry(BaseModel):
    """一条审计记录。

    回答四个问题：**谁**（``actor``）、**什么时候**（``created_at``）、
    **对什么做了什么**（``action`` + ``target``）、**结果如何**（``status``）。

    其余字段（trace_id / run_id / agent_name / tool_name）用于把这条记录
    挂回完整调用链，便于排查时串联。
    """

    id: int | None = None
    action: str
    status: AuditStatus = AuditStatus.SUCCESS
    target: str | None = None
    actor: str | None = None
    trace_id: str | None = None
    run_id: str | None = None
    agent_name: str | None = None
    tool_name: str | None = None
    detail: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryRecord(BaseModel):
    """一条长期记忆。"""

    id: int
    content: str
    session_id: str | None = None
    created_at: datetime


class RunAggregate(BaseModel):
    """运行记录的聚合结果，供 Evaluation 使用。"""

    runs: int = 0
    succeeded: int = 0
    failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    total_duration_ms: float = 0.0
    max_tool_calls: int = 0
    runs_with_tools: int = 0

    @property
    def success_rate(self) -> float:
        """成功率，无记录时为 0。"""
        return self.succeeded / self.runs if self.runs else 0.0

    @property
    def avg_duration_ms(self) -> float:
        """平均耗时，无记录时为 0。"""
        return self.total_duration_ms / self.runs if self.runs else 0.0

    @property
    def avg_total_tokens(self) -> float:
        """平均 token 消耗，无记录时为 0。"""
        return self.total_tokens / self.runs if self.runs else 0.0

    @property
    def avg_tool_calls(self) -> float:
        """平均工具调用次数，无记录时为 0。"""
        return self.total_tool_calls / self.runs if self.runs else 0.0


def _build_filter(
    clauses: list[tuple[str, Any]],
) -> tuple[str, tuple[Any, ...]]:
    """把 ``[(列, 值)]`` 拼成 WHERE 子句与参数元组。"""
    active = [(sql, value) for sql, value in clauses if value is not None]
    if not active:
        return "", ()
    where = "WHERE " + " AND ".join(sql for sql, _ in active)
    return where, tuple(value for _, value in active)


class AgentRepository:
    """``agents`` 表的数据访问。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    @staticmethod
    def _decode(payload: str) -> Agent:
        return Agent.model_validate(json.loads(payload))

    def add(self, agent: Agent, *, created_at: datetime) -> None:
        """插入一条新记录（主键冲突由调用方负责检查）。"""
        stamp = created_at.isoformat()
        self._db.execute(
            "INSERT INTO agents (name, payload, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (agent.name, agent.model_dump_json(), stamp, stamp),
        )

    def replace(self, agent: Agent, *, updated_at: datetime) -> None:
        """按名称覆盖已有记录。"""
        self._db.execute(
            "UPDATE agents SET payload = ?, updated_at = ? WHERE name = ?",
            (agent.model_dump_json(), updated_at.isoformat(), agent.name),
        )

    def remove(self, name: str) -> bool:
        return self._db.execute("DELETE FROM agents WHERE name = ?", (name,)) > 0

    def get(self, name: str) -> Agent | None:
        row = self._db.query_one("SELECT payload FROM agents WHERE name = ?", (name,))
        return self._decode(str(row["payload"])) if row is not None else None

    def exists(self, name: str) -> bool:
        return self._db.query_one("SELECT 1 FROM agents WHERE name = ?", (name,)) is not None

    def names(self) -> list[str]:
        return [str(row["name"]) for row in self._db.query("SELECT name FROM agents ORDER BY name")]

    def list(self) -> list[Agent]:
        rows = self._db.query("SELECT payload FROM agents ORDER BY name")
        return [self._decode(str(row["payload"])) for row in rows]

    def count(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) AS total FROM agents")
        return int(row["total"]) if row is not None else 0


class RunRepository:
    """``runs`` 表的数据访问。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    @staticmethod
    def _decode(payload: str) -> RunRecord:
        return RunRecord.model_validate(json.loads(payload))

    def add(self, record: RunRecord) -> None:
        """写入一条运行记录（同 run_id 覆盖）。"""
        self._db.execute(
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
                record.model_dump_json(),
            ),
        )

    def get(self, run_id: str) -> RunRecord | None:
        row = self._db.query_one("SELECT payload FROM runs WHERE run_id = ?", (run_id,))
        return self._decode(str(row["payload"])) if row is not None else None

    def list(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        status: RunStatus | None = None,
        since: datetime | None = None,
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[RunRecord]:
        """按条件查询，默认最新在前；``order='asc'`` 可改为最早在前。"""
        where, params = self._where(
            agent=agent, session_id=session_id, status=status, since=since
        )
        direction = "ASC" if str(order).lower() == "asc" else "DESC"
        sql = (
            "SELECT payload FROM runs "
            f"{where} ORDER BY created_at {direction}, rowid {direction} LIMIT ? OFFSET ?"
        )
        rows = self._db.query(sql, (*params, limit, offset))
        return [self._decode(str(row["payload"])) for row in rows]

    def count(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        status: RunStatus | None = None,
        since: datetime | None = None,
    ) -> int:
        where, params = self._where(
            agent=agent, session_id=session_id, status=status, since=since
        )
        row = self._db.query_one(f"SELECT COUNT(*) AS total FROM runs {where}", params)
        return int(row["total"]) if row is not None else 0

    def clear(self) -> int:
        return self._db.execute("DELETE FROM runs")

    def prune(self, keep: int) -> int:
        """只保留最近 ``keep`` 条，返回删除条数。"""
        return self._db.execute(
            "DELETE FROM runs WHERE run_id IN ("
            "  SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?"
            ")",
            (keep,),
        )

    def aggregate(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        since: datetime | None = None,
    ) -> RunAggregate:
        """用 SQL 聚合出 Evaluation 需要的基础计数与合计。"""
        where, params = self._where(agent=agent, session_id=session_id, since=since)
        row = self._db.query_one(
            "SELECT "
            "  COUNT(*) AS runs,"
            "  SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS succeeded,"
            "  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,"
            "  SUM(json_extract(payload, '$.prompt_tokens')) AS prompt_tokens,"
            "  SUM(json_extract(payload, '$.completion_tokens')) AS completion_tokens,"
            "  SUM(total_tokens) AS total_tokens,"
            "  SUM(tool_call_count) AS total_tool_calls,"
            "  SUM(duration_ms) AS total_duration_ms,"
            "  MAX(tool_call_count) AS max_tool_calls,"
            "  SUM(CASE WHEN tool_call_count > 0 THEN 1 ELSE 0 END) AS runs_with_tools "
            f"FROM runs {where}",
            params,
        )
        if row is None or not row["runs"]:
            return RunAggregate()
        return RunAggregate(
            runs=int(row["runs"] or 0),
            succeeded=int(row["succeeded"] or 0),
            failed=int(row["failed"] or 0),
            prompt_tokens=int(row["prompt_tokens"] or 0),
            completion_tokens=int(row["completion_tokens"] or 0),
            total_tokens=int(row["total_tokens"] or 0),
            total_tool_calls=int(row["total_tool_calls"] or 0),
            total_duration_ms=float(row["total_duration_ms"] or 0.0),
            max_tool_calls=int(row["max_tool_calls"] or 0),
            runs_with_tools=int(row["runs_with_tools"] or 0),
        )

    def durations(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        since: datetime | None = None,
    ) -> list[float]:
        """返回全部运行耗时，供计算分位数。"""
        where, params = self._where(agent=agent, session_id=session_id, since=since)
        rows = self._db.query(f"SELECT duration_ms FROM runs {where}", params)
        return sorted(float(row["duration_ms"] or 0.0) for row in rows)

    @staticmethod
    def _where(
        *,
        agent: str | None,
        session_id: str | None,
        status: RunStatus | None = None,
        since: datetime | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        clauses: list[tuple[str, Any]] = [
            ("agent = ?", agent),
            ("session_id = ?", session_id),
            ("status = ?", status.value if status else None),
            ("created_at >= ?", since.isoformat() if since else None),
        ]
        return _build_filter(clauses)


class MemoryRepository:
    """``memories`` 表的数据访问。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    @staticmethod
    def _to_record(row: Any) -> MemoryRecord:
        return MemoryRecord(
            id=int(row["id"]),
            content=str(row["content"]),
            session_id=row["session_id"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def add(self, *, content: str, session_id: str | None, created_at: datetime) -> MemoryRecord:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO memories (content, session_id, created_at) VALUES (?, ?, ?)",
                (content, session_id, created_at.isoformat()),
            )
            memory_id = int(cursor.lastrowid or 0)
        return MemoryRecord(
            id=memory_id, content=content, session_id=session_id, created_at=created_at
        )

    def get(self, memory_id: int) -> MemoryRecord | None:
        row = self._db.query_one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        return self._to_record(row) if row is not None else None

    def list(self, *, limit: int = 50) -> list[MemoryRecord]:
        rows = self._db.query(
            "SELECT * FROM memories ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        )
        return [self._to_record(row) for row in rows]

    def search(self, *, terms: Sequence[str], limit: int) -> list[MemoryRecord]:
        """按关键词加权召回：命中词越长得分越高。"""
        if not terms:
            return []
        score_parts = ["CASE WHEN lower(content) LIKE ? THEN ? ELSE 0 END" for _ in terms]
        params: list[Any] = []
        for term in terms:
            params.append(f"%{term.lower()}%")
            params.append(len(term))
        params.append(limit)

        sql = (
            "SELECT * FROM ("
            "  SELECT *, ("
            + " + ".join(score_parts)
            + ") AS score FROM memories"
            ") WHERE score > 0 "
            "ORDER BY score DESC, created_at DESC, id DESC LIMIT ?"
        )
        rows = self._db.query(sql, params)
        return [self._to_record(row) for row in rows]

    def remove(self, memory_id: int) -> bool:
        return self._db.execute("DELETE FROM memories WHERE id = ?", (memory_id,)) > 0

    def clear(self) -> int:
        return self._db.execute("DELETE FROM memories")

    def count(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) AS total FROM memories")
        return int(row["total"]) if row is not None else 0

class AuditRepository:
    """``audit_logs`` 表的数据访问。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    @staticmethod
    def _to_entry(row: Any) -> AuditEntry:
        return AuditEntry(
            id=int(row["id"]),
            action=str(row["action"]),
            status=AuditStatus(str(row["status"])),
            target=row["target"],
            actor=row["actor"],
            trace_id=row["trace_id"],
            run_id=row["run_id"],
            agent_name=row["agent_name"],
            tool_name=row["tool_name"],
            detail=str(row["detail"] or ""),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def add(self, entry: AuditEntry) -> AuditEntry:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO audit_logs "
                "(action, status, target, actor, trace_id, run_id, "
                " agent_name, tool_name, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.action,
                    entry.status.value,
                    entry.target,
                    entry.actor,
                    entry.trace_id,
                    entry.run_id,
                    entry.agent_name,
                    entry.tool_name,
                    entry.detail,
                    entry.created_at.isoformat(),
                ),
            )
            entry_id = int(cursor.lastrowid or 0)
        return entry.model_copy(update={"id": entry_id})

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
        where, params = _build_filter(
            [
                ("action = ?", action),
                ("actor = ?", actor),
                ("run_id = ?", run_id),
                ("status = ?", status.value if status else None),
            ]
        )
        direction = "ASC" if str(order).lower() == "asc" else "DESC"
        rows = self._db.query(
            f"SELECT * FROM audit_logs {where} "
            f"ORDER BY created_at {direction}, id {direction} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [self._to_entry(row) for row in rows]

    def count(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        run_id: str | None = None,
        status: AuditStatus | None = None,
    ) -> int:
        where, params = _build_filter(
            [
                ("action = ?", action),
                ("actor = ?", actor),
                ("run_id = ?", run_id),
                ("status = ?", status.value if status else None),
            ]
        )
        row = self._db.query_one(f"SELECT COUNT(*) AS total FROM audit_logs {where}", params)
        return int(row["total"]) if row is not None else 0

    def prune(self, keep: int) -> int:
        """只保留最近 ``keep`` 条，返回删除条数。"""
        return self._db.execute(
            "DELETE FROM audit_logs WHERE id IN ("
            "  SELECT id FROM audit_logs ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?"
            ")",
            (keep,),
        )

    def clear(self) -> int:
        return self._db.execute("DELETE FROM audit_logs")


class ApiKeyRepository:
    """``api_keys`` 表的数据访问。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    @staticmethod
    def _to_record(row: Any) -> ApiKeyRecord:
        return ApiKeyRecord(
            id=int(row["id"]),
            key_hash=str(row["key_hash"]),
            name=str(row["name"]),
            permissions=list(json.loads(str(row["permissions"]))),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            last_used_at=(
                datetime.fromisoformat(str(row["last_used_at"]))
                if row["last_used_at"]
                else None
            ),
            revoked_at=(
                datetime.fromisoformat(str(row["revoked_at"]))
                if row["revoked_at"]
                else None
            ),
        )

    def add(self, record: ApiKeyRecord) -> ApiKeyRecord:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO api_keys "
                "(key_hash, name, permissions, created_at, last_used_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.key_hash,
                    record.name,
                    json.dumps(record.permissions, ensure_ascii=False),
                    record.created_at.isoformat(),
                    record.last_used_at.isoformat() if record.last_used_at else None,
                    record.revoked_at.isoformat() if record.revoked_at else None,
                ),
            )
            return record.model_copy(update={"id": int(cursor.lastrowid or 0)})

    def get_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        row = self._db.query_one(
            "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
        )
        return self._to_record(row) if row is not None else None

    def get(self, key_id: int) -> ApiKeyRecord | None:
        row = self._db.query_one("SELECT * FROM api_keys WHERE id = ?", (key_id,))
        return self._to_record(row) if row is not None else None

    def get_by_name(self, name: str) -> ApiKeyRecord | None:
        row = self._db.query_one("SELECT * FROM api_keys WHERE name = ?", (name,))
        return self._to_record(row) if row is not None else None

    def list(self, *, include_revoked: bool = False) -> list[ApiKeyRecord]:
        where = "" if include_revoked else "WHERE revoked_at IS NULL"
        rows = self._db.query(f"SELECT * FROM api_keys {where} ORDER BY id")
        return [self._to_record(row) for row in rows]

    def touch(self, key_hash: str, *, used_at: datetime) -> None:
        """记录一次成功使用的时间。"""
        self._db.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
            (used_at.isoformat(), key_hash),
        )

    def revoke(self, key_id: int, *, revoked_at: datetime) -> bool:
        """吊销密钥（软删除，保留审计线索）。"""
        return (
            self._db.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (revoked_at.isoformat(), key_id),
            )
            > 0
        )

    def count(self, *, include_revoked: bool = False) -> int:
        where = "" if include_revoked else "WHERE revoked_at IS NULL"
        row = self._db.query_one(f"SELECT COUNT(*) AS total FROM api_keys {where}")
        return int(row["total"]) if row is not None else 0

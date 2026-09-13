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

from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.database.connection import Database
from agentos.database.models import AgentRecord
from agentos.database.repository import Repository
from agentos.database.repository import build_filter as _build_filter
from agentos.runtime.agent import Agent
from agentos.runtime.message import Message

AGENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    system_prompt TEXT,
    model TEXT,
    temperature REAL,
    max_iterations INTEGER,
    tools TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, name)
);
CREATE INDEX IF NOT EXISTS idx_agents_workspace_name
    ON agents (workspace_id, name);
"""

RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    user_id INTEGER,
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
CREATE INDEX IF NOT EXISTS idx_runs_workspace_created
    ON runs (workspace_id, created_at DESC);
"""

API_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL DEFAULT 1,
    workspace_id INTEGER NOT NULL DEFAULT 1,
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
    workspace_id INTEGER NOT NULL DEFAULT 1,
    user_id INTEGER,
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
CREATE INDEX IF NOT EXISTS idx_audit_workspace_created
    ON audit_logs (workspace_id, created_at DESC);
"""

MEMORIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    user_id INTEGER,
    scope TEXT NOT NULL DEFAULT 'workspace',
    content TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_workspace_created
    ON memories (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_workspace_user
    ON memories (workspace_id, user_id, scope);
"""


class RunStatus(StrEnum):
    """运行状态。"""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunRecord(BaseModel):
    """一次运行的记录。"""

    run_id: str
    workspace_id: int = DEFAULT_WORKSPACE_ID
    user_id: int | None = None
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
    user_id: int = DEFAULT_USER_ID
    workspace_id: int = DEFAULT_WORKSPACE_ID
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
    workspace_id: int = DEFAULT_WORKSPACE_ID
    user_id: int | None = None
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


class MemoryScope(StrEnum):
    """Visibility scope for a long-term memory."""

    USER = "user"
    WORKSPACE = "workspace"


class MemoryRecord(BaseModel):
    """???????"""

    id: int
    workspace_id: int = DEFAULT_WORKSPACE_ID
    user_id: int | None = None
    scope: MemoryScope = MemoryScope.WORKSPACE
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


class AgentRepository(Repository):
    """Workspace-scoped access to the ``agents`` table."""

    _LEGACY_COLUMNS = {
        "id": "INTEGER",
        "description": "TEXT NOT NULL DEFAULT ''",
        "system_prompt": "TEXT",
        "model": "TEXT",
        "temperature": "REAL",
        "max_iterations": "INTEGER",
        "tools": "TEXT NOT NULL DEFAULT '[]'",
        "metadata": "TEXT NOT NULL DEFAULT '{}'",
    }

    def __init__(self, database: Database) -> None:
        self._db = database
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        """Upgrade legacy Agent tables and migrate to Workspace uniqueness."""
        self._db.ensure_columns(
            "agents",
            self._LEGACY_COLUMNS,
            backfill="UPDATE agents SET id = rowid WHERE id IS NULL",
        )
        self._backfill_legacy_payload()
        columns = {
            str(row["name"])
            for row in self._db.query("PRAGMA table_info(agents)")
        }
        if "workspace_id" not in columns:
            self._migrate_workspace_schema()

    def _migrate_workspace_schema(self) -> None:
        """Rebuild the table so uniqueness becomes ``(workspace_id, name)``."""
        with self._db.transaction() as conn:
            conn.execute("ALTER TABLE agents RENAME TO agents_legacy")
            conn.executescript(AGENTS_SCHEMA)
            conn.execute(
                "INSERT INTO agents "
                "(id, workspace_id, name, description, system_prompt, model, "
                " temperature, max_iterations, tools, metadata, payload, "
                " created_at, updated_at) "
                "SELECT id, 1, name, description, system_prompt, model, "
                "       temperature, max_iterations, tools, metadata, payload, "
                "       created_at, updated_at "
                "FROM agents_legacy"
            )
            conn.execute("DROP TABLE agents_legacy")

    def _backfill_legacy_payload(self) -> None:
        """Populate structured columns from the legacy JSON payload."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT name, payload, description, system_prompt, model, "
                "temperature, max_iterations, tools, metadata FROM agents"
            ).fetchall()
            for row in rows:
                payload = self._payload(row)
                updates: dict[str, Any] = {}
                if not row["description"] and payload.get("description"):
                    updates["description"] = payload["description"]
                for field in ("system_prompt", "model", "temperature", "max_iterations"):
                    if row[field] is None and payload.get(field) is not None:
                        updates[field] = payload[field]
                if (not row["tools"] or row["tools"] == "[]") and payload.get("tools"):
                    updates["tools"] = json.dumps(payload["tools"], ensure_ascii=False)
                if (not row["metadata"] or row["metadata"] == "{}") and payload.get("metadata"):
                    updates["metadata"] = json.dumps(
                        payload["metadata"], ensure_ascii=False
                    )
                if not updates:
                    continue
                assignments = ", ".join(f"{column} = ?" for column in updates)
                conn.execute(
                    f"UPDATE agents SET {assignments} WHERE name = ?",
                    (*updates.values(), row["name"]),
                )

    @staticmethod
    def _payload(row: Any) -> dict[str, Any]:
        raw = row["payload"]
        try:
            value = json.loads(str(raw)) if raw else {}
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _decode(self, row: Any) -> Agent:
        payload = self._payload(row)
        return Agent(
            name=str(row["name"]),
            description=str(row["description"] or payload.get("description") or ""),
            system_prompt=(
                row["system_prompt"]
                if row["system_prompt"] is not None
                else payload.get("system_prompt")
            ),
            model=row["model"] if row["model"] is not None else payload.get("model"),
            temperature=(
                row["temperature"]
                if row["temperature"] is not None
                else payload.get("temperature")
            ),
            max_iterations=(
                row["max_iterations"]
                if row["max_iterations"] is not None
                else payload.get("max_iterations")
            ),
            tools=(
                json.loads(str(row["tools"] or "[]"))
                if row["tools"]
                else payload.get("tools", [])
            ),
            metadata=(
                json.loads(str(row["metadata"] or "{}"))
                if row["metadata"]
                else payload.get("metadata", {})
            ),
        )

    def _to_record(self, row: Any) -> AgentRecord:
        agent = self._decode(row)
        return AgentRecord(
            id=int(row["id"]) if row["id"] is not None else None,
            workspace_id=int(row["workspace_id"]),
            name=agent.name,
            description=agent.description,
            system_prompt=agent.system_prompt,
            model=agent.model,
            temperature=agent.temperature,
            max_iterations=agent.max_iterations,
            tools=list(agent.tools),
            metadata=dict(agent.metadata),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _values(
        agent: Agent, *, created_at: datetime, updated_at: datetime
    ) -> tuple[Any, ...]:
        return (
            agent.name,
            agent.description,
            agent.system_prompt,
            agent.model,
            agent.temperature,
            agent.max_iterations,
            json.dumps(agent.tools, ensure_ascii=False),
            json.dumps(agent.metadata, ensure_ascii=False),
            agent.model_dump_json(),
            created_at.isoformat(),
            updated_at.isoformat(),
        )

    def add(
        self,
        agent: Agent,
        *,
        created_at: datetime,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
    ) -> AgentRecord:
        values = self._values(agent, created_at=created_at, updated_at=created_at)
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO agents "
                "(workspace_id, name, description, system_prompt, model, "
                " temperature, max_iterations, tools, metadata, payload, "
                " created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (workspace_id, *values),
            )
            record_id = int(cursor.lastrowid or 0)
            conn.execute(
                "UPDATE agents SET id = ? WHERE workspace_id = ? AND name = ?",
                (record_id, workspace_id, agent.name),
            )
        return AgentRecord(
            id=record_id,
            workspace_id=workspace_id,
            name=agent.name,
            description=agent.description,
            system_prompt=agent.system_prompt,
            model=agent.model,
            temperature=agent.temperature,
            max_iterations=agent.max_iterations,
            tools=list(agent.tools),
            metadata=dict(agent.metadata),
            created_at=created_at,
            updated_at=created_at,
        )

    def replace(
        self,
        agent: Agent,
        *,
        updated_at: datetime,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
    ) -> AgentRecord:
        existing = self.get_record(agent.name, workspace_id=workspace_id)
        if existing is None:
            return self.add(agent, created_at=updated_at, workspace_id=workspace_id)
        self._db.execute(
            "UPDATE agents SET "
            "description = ?, system_prompt = ?, model = ?, temperature = ?, "
            "max_iterations = ?, tools = ?, metadata = ?, payload = ?, updated_at = ? "
            "WHERE workspace_id = ? AND name = ?",
            (
                agent.description,
                agent.system_prompt,
                agent.model,
                agent.temperature,
                agent.max_iterations,
                json.dumps(agent.tools, ensure_ascii=False),
                json.dumps(agent.metadata, ensure_ascii=False),
                agent.model_dump_json(),
                updated_at.isoformat(),
                workspace_id,
                agent.name,
            ),
        )
        return existing.model_copy(
            update={
                "description": agent.description,
                "system_prompt": agent.system_prompt,
                "model": agent.model,
                "temperature": agent.temperature,
                "max_iterations": agent.max_iterations,
                "tools": list(agent.tools),
                "metadata": dict(agent.metadata),
                "updated_at": updated_at,
            }
        )

    def remove(self, name: str, *, workspace_id: int = DEFAULT_WORKSPACE_ID) -> bool:
        return (
            self._db.execute(
                "DELETE FROM agents WHERE workspace_id = ? AND name = ?",
                (workspace_id, name),
            )
            > 0
        )

    def get_record(
        self, name: str, *, workspace_id: int = DEFAULT_WORKSPACE_ID
    ) -> AgentRecord | None:
        row = self._db.query_one(
            "SELECT * FROM agents WHERE workspace_id = ? AND name = ?",
            (workspace_id, name),
        )
        return self._to_record(row) if row is not None else None

    def get(self, name: str, *, workspace_id: int = DEFAULT_WORKSPACE_ID) -> Agent | None:
        row = self._db.query_one(
            "SELECT * FROM agents WHERE workspace_id = ? AND name = ?",
            (workspace_id, name),
        )
        return self._decode(row) if row is not None else None

    def exists(self, name: str, *, workspace_id: int = DEFAULT_WORKSPACE_ID) -> bool:
        return (
            self._db.query_one(
                "SELECT 1 FROM agents WHERE workspace_id = ? AND name = ?",
                (workspace_id, name),
            )
            is not None
        )

    def names(self, *, workspace_id: int = DEFAULT_WORKSPACE_ID) -> list[str]:
        rows = self._db.query(
            "SELECT name FROM agents WHERE workspace_id = ? ORDER BY name",
            (workspace_id,),
        )
        return [str(row["name"]) for row in rows]

    def list_records(
        self,
        *,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AgentRecord]:
        sql = "SELECT * FROM agents WHERE workspace_id = ? ORDER BY name"
        params: tuple[Any, ...] = (workspace_id,)
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = (workspace_id, limit, offset)
        rows = self._db.query(sql, params)
        return [self._to_record(row) for row in rows]

    def list(self, *, workspace_id: int = DEFAULT_WORKSPACE_ID) -> list[Agent]:
        rows = self._db.query(
            "SELECT * FROM agents WHERE workspace_id = ? ORDER BY name",
            (workspace_id,),
        )
        return [self._decode(row) for row in rows]

    def count(self, *, workspace_id: int = DEFAULT_WORKSPACE_ID) -> int:
        row = self._db.query_one(
            "SELECT COUNT(*) AS total FROM agents WHERE workspace_id = ?",
            (workspace_id,),
        )
        return int(row["total"]) if row is not None else 0


class RunRepository(Repository):
    """Workspace-scoped access to the ``runs`` table."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._db.ensure_columns(
            "runs",
            {
                "workspace_id": "INTEGER NOT NULL DEFAULT 1",
                "user_id": "INTEGER",
            },
            backfill=(
                "UPDATE runs SET workspace_id = 1 WHERE workspace_id IS NULL; "
                "UPDATE runs SET user_id = 1 WHERE user_id IS NULL"
            ),
        )

    @staticmethod
    def _decode(row: Any) -> RunRecord:
        payload = json.loads(str(row["payload"]))
        payload["workspace_id"] = int(row["workspace_id"] or DEFAULT_WORKSPACE_ID)
        payload["user_id"] = row["user_id"]
        return RunRecord.model_validate(payload)

    def add(self, record: RunRecord) -> None:
        """写入一条运行记录（同 run_id 覆盖）。"""
        self._db.execute(
            "INSERT OR REPLACE INTO runs "
            "(run_id, workspace_id, user_id, agent, session_id, status, "
            " created_at, duration_ms, total_tokens, tool_call_count, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.run_id,
                record.workspace_id,
                record.user_id,
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

    def get(
        self, run_id: str, *, workspace_id: int = DEFAULT_WORKSPACE_ID
    ) -> RunRecord | None:
        row = self._db.query_one(
            "SELECT * FROM runs WHERE run_id = ? AND workspace_id = ?",
            (run_id, workspace_id),
        )
        return self._decode(row) if row is not None else None

    def create_run(self, record: RunRecord) -> None:
        """Compatibility name for creating a run record."""
        self.add(record)

    def finish_run(self, record: RunRecord) -> None:
        """Compatibility name for persisting the final run state."""
        self.add(record)

    def list(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        status: RunStatus | None = None,
        since: datetime | None = None,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[RunRecord]:
        """按 Workspace 和条件查询，默认最新在前。"""
        where, params = self._where(
            workspace_id=workspace_id,
            agent=agent,
            session_id=session_id,
            status=status,
            since=since,
        )
        direction = "ASC" if str(order).lower() == "asc" else "DESC"
        sql = (
            "SELECT * FROM runs "
            f"{where} ORDER BY created_at {direction}, rowid {direction} LIMIT ? OFFSET ?"
        )
        rows = self._db.query(sql, (*params, limit, offset))
        return [self._decode(row) for row in rows]

    def count(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        status: RunStatus | None = None,
        since: datetime | None = None,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
    ) -> int:
        where, params = self._where(
            workspace_id=workspace_id,
            agent=agent,
            session_id=session_id,
            status=status,
            since=since,
        )
        row = self._db.query_one(f"SELECT COUNT(*) AS total FROM runs {where}", params)
        return int(row["total"]) if row is not None else 0

    def clear(self, *, workspace_id: int | None = None) -> int:
        if workspace_id is None:
            return self._db.execute("DELETE FROM runs")
        return self._db.execute(
            "DELETE FROM runs WHERE workspace_id = ?", (workspace_id,)
        )

    def prune(self, keep: int, *, workspace_id: int = DEFAULT_WORKSPACE_ID) -> int:
        """只保留当前 Workspace 最近 ``keep`` 条。"""
        return self._db.execute(
            "DELETE FROM runs WHERE workspace_id = ? AND run_id IN ("
            "  SELECT run_id FROM runs WHERE workspace_id = ? "
            "  ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?"
            ")",
            (workspace_id, workspace_id, keep),
        )

    def aggregate(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
    ) -> RunAggregate:
        """? SQL ????? Workspace ?????????"""
        where, params = self._where(
            workspace_id=workspace_id,
            agent=agent,
            session_id=session_id,
            since=since,
            until=until,
        )
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
        until: datetime | None = None,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
    ) -> list[float]:
        """???? Workspace ?????????????"""
        where, params = self._where(
            workspace_id=workspace_id,
            agent=agent,
            session_id=session_id,
            since=since,
            until=until,
        )
        rows = self._db.query(f"SELECT duration_ms FROM runs {where}", params)
        return sorted(float(row["duration_ms"] or 0.0) for row in rows)

    @staticmethod
    def _where(
        *,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        agent: str | None,
        session_id: str | None,
        status: RunStatus | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        clauses: list[tuple[str, Any]] = [
            ("workspace_id = ?", workspace_id),
            ("agent = ?", agent),
            ("session_id = ?", session_id),
            ("status = ?", status.value if status else None),
            ("created_at >= ?", since.isoformat() if since else None),
            ("created_at < ?", until.isoformat() if until else None),
        ]
        return _build_filter(clauses)


class MemoryRepository(Repository):
    """Workspace and user scoped access to ``memories``."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._db.ensure_columns(
            "memories",
            {
                "workspace_id": "INTEGER NOT NULL DEFAULT 1",
                "user_id": "INTEGER",
                "scope": "TEXT NOT NULL DEFAULT 'workspace'",
            },
            backfill=(
                "UPDATE memories SET workspace_id = 1 WHERE workspace_id IS NULL; "
                "UPDATE memories SET user_id = 1 WHERE user_id IS NULL; "
                "UPDATE memories SET scope = 'workspace' WHERE scope IS NULL"
            ),
        )

    @staticmethod
    def _to_record(row: Any) -> MemoryRecord:
        return MemoryRecord(
            id=int(row["id"]),
            workspace_id=int(row["workspace_id"] or DEFAULT_WORKSPACE_ID),
            user_id=int(row["user_id"]) if row["user_id"] is not None else None,
            scope=MemoryScope(str(row["scope"] or MemoryScope.WORKSPACE)),
            content=str(row["content"]),
            session_id=row["session_id"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _visibility_clause(
        *, workspace_id: int, user_id: int | None, scope: MemoryScope | None
    ) -> tuple[str, tuple[Any, ...]]:
        if scope == MemoryScope.USER:
            return "workspace_id = ? AND scope = 'user' AND user_id = ?", (
                workspace_id,
                user_id,
            )
        if scope == MemoryScope.WORKSPACE:
            return "workspace_id = ? AND scope = 'workspace'", (workspace_id,)
        if user_id is None:
            return "workspace_id = ? AND scope = 'workspace'", (workspace_id,)
        return (
            "workspace_id = ? AND (scope = 'workspace' "
            "OR (scope = 'user' AND user_id = ?))",
            (workspace_id, user_id),
        )

    def add(
        self,
        *,
        content: str,
        session_id: str | None,
        created_at: datetime,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        user_id: int | None = None,
        scope: MemoryScope = MemoryScope.WORKSPACE,
    ) -> MemoryRecord:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO memories "
                "(workspace_id, user_id, scope, content, session_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    workspace_id,
                    user_id,
                    scope.value,
                    content,
                    session_id,
                    created_at.isoformat(),
                ),
            )
            memory_id = int(cursor.lastrowid or 0)
        return MemoryRecord(
            id=memory_id,
            workspace_id=workspace_id,
            user_id=user_id,
            scope=scope,
            content=content,
            session_id=session_id,
            created_at=created_at,
        )

    def get(
        self,
        memory_id: int,
        *,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        user_id: int | None = None,
    ) -> MemoryRecord | None:
        visibility, params = self._visibility_clause(
            workspace_id=workspace_id, user_id=user_id, scope=None
        )
        row = self._db.query_one(
            f"SELECT * FROM memories WHERE id = ? AND {visibility}",
            (memory_id, *params),
        )
        return self._to_record(row) if row is not None else None

    def list(
        self,
        *,
        limit: int = 50,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        user_id: int | None = None,
        scope: MemoryScope | None = None,
    ) -> list[MemoryRecord]:
        visibility, params = self._visibility_clause(
            workspace_id=workspace_id, user_id=user_id, scope=scope
        )
        rows = self._db.query(
            f"SELECT * FROM memories WHERE {visibility} "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (*params, limit),
        )
        return [self._to_record(row) for row in rows]

    def save_memory(
        self,
        *,
        content: str,
        session_id: str | None,
        created_at: datetime,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        user_id: int | None = None,
        scope: MemoryScope = MemoryScope.WORKSPACE,
    ) -> MemoryRecord:
        """Compatibility name for writing a memory record."""
        return self.add(
            content=content,
            session_id=session_id,
            created_at=created_at,
            workspace_id=workspace_id,
            user_id=user_id,
            scope=scope,
        )

    def search_memory(
        self,
        *,
        terms: Sequence[str],
        limit: int,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        user_id: int | None = None,
        scope: MemoryScope | None = None,
    ) -> list[MemoryRecord]:
        """Compatibility name for keyword search."""
        return self.search(
            terms=terms,
            limit=limit,
            workspace_id=workspace_id,
            user_id=user_id,
            scope=scope,
        )

    def search(
        self,
        *,
        terms: Sequence[str],
        limit: int,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        user_id: int | None = None,
        scope: MemoryScope | None = None,
    ) -> list[MemoryRecord]:
        """按关键词加权召回，并强制应用 tenant visibility。"""
        if not terms:
            return []
        visibility, visibility_params = self._visibility_clause(
            workspace_id=workspace_id, user_id=user_id, scope=scope
        )
        score_parts = ["CASE WHEN lower(content) LIKE ? THEN ? ELSE 0 END" for _ in terms]
        score_params: list[Any] = []
        for term in terms:
            score_params.extend((f"%{term.lower()}%", len(term)))
        sql = (
            "SELECT * FROM ("
            "  SELECT *, ("
            + " + ".join(score_parts)
            + ") AS score FROM memories "
            f"WHERE {visibility}"
            ") WHERE score > 0 "
            "ORDER BY score DESC, created_at DESC, id DESC LIMIT ?"
        )
        rows = self._db.query(
            sql, (*score_params, *visibility_params, limit)
        )
        return [self._to_record(row) for row in rows]

    def remove(
        self,
        memory_id: int,
        *,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        user_id: int | None = None,
    ) -> bool:
        visibility, params = self._visibility_clause(
            workspace_id=workspace_id, user_id=user_id, scope=None
        )
        return self._db.execute(
            f"DELETE FROM memories WHERE id = ? AND {visibility}",
            (memory_id, *params),
        ) > 0

    def clear(
        self,
        *,
        workspace_id: int | None = None,
        user_id: int | None = None,
    ) -> int:
        if workspace_id is None:
            return self._db.execute("DELETE FROM memories")
        visibility, params = self._visibility_clause(
            workspace_id=workspace_id, user_id=user_id, scope=None
        )
        return self._db.execute(f"DELETE FROM memories WHERE {visibility}", params)

    def count(
        self,
        *,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        user_id: int | None = None,
    ) -> int:
        visibility, params = self._visibility_clause(
            workspace_id=workspace_id, user_id=user_id, scope=None
        )
        row = self._db.query_one(
            f"SELECT COUNT(*) AS total FROM memories WHERE {visibility}", params
        )
        return int(row["total"]) if row is not None else 0


class AuditRepository(Repository):
    """Workspace-scoped access to ``audit_logs``."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._db.ensure_columns(
            "audit_logs",
            {
                "workspace_id": "INTEGER NOT NULL DEFAULT 1",
                "user_id": "INTEGER",
            },
            backfill=(
                "UPDATE audit_logs SET workspace_id = 1 WHERE workspace_id IS NULL; "
                "UPDATE audit_logs SET user_id = 1 WHERE user_id IS NULL"
            ),
        )

    @staticmethod
    def _to_entry(row: Any) -> AuditEntry:
        return AuditEntry(
            id=int(row["id"]),
            workspace_id=int(row["workspace_id"] or DEFAULT_WORKSPACE_ID),
            user_id=int(row["user_id"]) if row["user_id"] is not None else None,
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
                "(workspace_id, user_id, action, status, target, actor, "
                " trace_id, run_id, agent_name, tool_name, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.workspace_id,
                    entry.user_id,
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
        workspace_id: int = DEFAULT_WORKSPACE_ID,
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
                ("workspace_id = ?", workspace_id),
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
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        action: str | None = None,
        actor: str | None = None,
        run_id: str | None = None,
        status: AuditStatus | None = None,
    ) -> int:
        where, params = _build_filter(
            [
                ("workspace_id = ?", workspace_id),
                ("action = ?", action),
                ("actor = ?", actor),
                ("run_id = ?", run_id),
                ("status = ?", status.value if status else None),
            ]
        )
        row = self._db.query_one(f"SELECT COUNT(*) AS total FROM audit_logs {where}", params)
        return int(row["total"]) if row is not None else 0

    def prune(self, keep: int, *, workspace_id: int | None = None) -> int:
        """只保留当前 Workspace 最近 ``keep`` 条。"""
        if workspace_id is None:
            return self._db.execute(
                "DELETE FROM audit_logs WHERE id IN ("
                "  SELECT id FROM audit_logs ORDER BY created_at DESC, id DESC "
                "  LIMIT -1 OFFSET ?"
                ")",
                (keep,),
            )
        return self._db.execute(
            "DELETE FROM audit_logs WHERE workspace_id = ? AND id IN ("
            "  SELECT id FROM audit_logs WHERE workspace_id = ? "
            "  ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?"
            ")",
            (workspace_id, workspace_id, keep),
        )

    def clear(self, *, workspace_id: int | None = None) -> int:
        if workspace_id is None:
            return self._db.execute("DELETE FROM audit_logs")
        return self._db.execute(
            "DELETE FROM audit_logs WHERE workspace_id = ?", (workspace_id,)
        )


class ApiKeyRepository(Repository):
    """``api_keys`` 表的数据访问。"""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._db.ensure_columns(
            "api_keys",
            {
                "user_id": "INTEGER NOT NULL DEFAULT 1",
                "workspace_id": "INTEGER NOT NULL DEFAULT 1",
            },
            backfill=(
                "UPDATE api_keys SET user_id = 1 WHERE user_id IS NULL; "
                "UPDATE api_keys SET workspace_id = 1 WHERE workspace_id IS NULL"
            ),
        )

    @staticmethod
    def _to_record(row: Any) -> ApiKeyRecord:
        return ApiKeyRecord(
            id=int(row["id"]),
            key_hash=str(row["key_hash"]),
            name=str(row["name"]),
            user_id=int(row["user_id"] or DEFAULT_USER_ID),
            workspace_id=int(row["workspace_id"] or DEFAULT_WORKSPACE_ID),
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
                "(key_hash, name, user_id, workspace_id, permissions, "
                " created_at, last_used_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.key_hash,
                    record.name,
                    record.user_id,
                    record.workspace_id,
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

    def list(
        self,
        *,
        include_revoked: bool = False,
        workspace_id: int | None = None,
    ) -> list[ApiKeyRecord]:
        clauses = []
        params: list[Any] = []
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._db.query(
            f"SELECT * FROM api_keys {where} ORDER BY id", params
        )
        return [self._to_record(row) for row in rows]

    def touch(self, key_hash: str, *, used_at: datetime) -> None:
        """记录一次成功使用的时间。"""
        self._db.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
            (used_at.isoformat(), key_hash),
        )

    def revoke(
        self,
        key_id: int,
        *,
        revoked_at: datetime,
        workspace_id: int | None = None,
    ) -> bool:
        """吊销密钥（软删除，保留审计线索）。"""
        where = "id = ? AND revoked_at IS NULL"
        params: list[Any] = [revoked_at.isoformat(), key_id]
        if workspace_id is not None:
            where += " AND workspace_id = ?"
            params.append(workspace_id)
        return self._db.execute(
            f"UPDATE api_keys SET revoked_at = ? WHERE {where}", params
        ) > 0

    def count(
        self, *, include_revoked: bool = False, workspace_id: int | None = None
    ) -> int:
        clauses = []
        params: list[Any] = []
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self._db.query_one(
            f"SELECT COUNT(*) AS total FROM api_keys {where}", params
        )
        return int(row["total"]) if row is not None else 0

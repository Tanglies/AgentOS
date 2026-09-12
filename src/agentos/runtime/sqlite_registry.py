"""把 Agent 定义持久化到 SQLite 的注册表。

接口与内存版 :class:`~agentos.runtime.registry.AgentRegistry` 一致，
区别是进程重启后 Agent 不会丢失。

存储方式：直接把 ``Agent`` 序列化成 JSON 存进 ``payload`` 列。
不为每个字段建列的原因是 —— Agent 定义仍在快速演进（工具、记忆、
规划都会往上挂），JSON 列不需要每次加字段都改表结构。
代价是无法按字段索引查询，但 Agent 数量少，直接全量读出来即可。

.. note::

   Agent 名是主键，重名注册默认抛 :class:`~agentos.core.exceptions.ConflictError`，
   与内存版行为一致。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from agentos.core.exceptions import ConflictError, NotFoundError
from agentos.runtime.agent import Agent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SQLiteAgentRegistry:
    """基于 SQLite 的 Agent 注册表。"""

    def __init__(self, db_path: str, agents: Iterable[Agent] | None = None) -> None:
        self.path = Path(db_path).expanduser()
        if self.path.parent != Path(""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        for agent in agents or ():
            self.register(agent)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """打开连接并在退出时关闭（``with conn`` 只管理事务，不关连接）。"""
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _decode(payload: str) -> Agent:
        return Agent.model_validate(json.loads(payload))

    def register(self, agent: Agent, *, overwrite: bool = False) -> Agent:
        """注册 Agent；重名时默认抛 :class:`ConflictError`。"""
        now = datetime.now(UTC).isoformat()
        payload = agent.model_dump_json()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT name FROM agents WHERE name = ?", (agent.name,)
            ).fetchone()
            if existing is not None and not overwrite:
                raise ConflictError(
                    f"agent already registered: {agent.name}",
                    details={"agent": agent.name},
                )
            if existing is None:
                conn.execute(
                    "INSERT INTO agents (name, payload, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (agent.name, payload, now, now),
                )
            else:
                conn.execute(
                    "UPDATE agents SET payload = ?, updated_at = ? WHERE name = ?",
                    (payload, now, agent.name),
                )
        return agent

    def unregister(self, name: str) -> None:
        """注销 Agent，不存在时报错。"""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM agents WHERE name = ?", (name,))
        if cursor.rowcount == 0:
            raise NotFoundError(f"agent not found: {name}", details={"agent": name})

    def get(self, name: str) -> Agent:
        """按名称获取 Agent。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM agents WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            with self._connect() as conn:
                available = [
                    item["name"]
                    for item in conn.execute(
                        "SELECT name FROM agents ORDER BY name"
                    ).fetchall()
                ]
            raise NotFoundError(
                f"agent not found: {name}",
                details={"agent": name, "available": available},
            )
        return self._decode(str(row["payload"]))

    def list(self) -> list[Agent]:
        """返回全部 Agent（按名称排序）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM agents ORDER BY name"
            ).fetchall()
        return [self._decode(str(row["payload"])) for row in rows]

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM agents WHERE name = ?", (name,)
            ).fetchone()
        return row is not None

    def __len__(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM agents").fetchone()
        return int(row["total"]) if row is not None else 0


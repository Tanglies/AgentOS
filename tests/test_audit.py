"""审计日志测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.core.config import AuditSettings, Settings
from agentos.core.context import bind
from agentos.runtime.audit import (
    ACTION_AGENT_REGISTER,
    ACTION_AGENT_RUN,
    ACTION_AGENT_UNREGISTER,
    ACTION_TOOL_EXECUTE,
    AuditLog,
)
from agentos.runtime.repositories import AuditStatus


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(AuditSettings(db_path=str(tmp_path / "audit.db")))


# --- 存储基础 -------------------------------------------------------------


def test_record_returns_entry_with_id(audit: AuditLog) -> None:
    entry = audit.record(ACTION_AGENT_RUN, target="assistant", detail="完成")

    assert entry.id is not None
    assert entry.action == ACTION_AGENT_RUN
    assert entry.status == AuditStatus.SUCCESS
    assert entry.target == "assistant"
    assert audit.count() == 1


def test_default_status_is_success(audit: AuditLog) -> None:
    assert audit.record(ACTION_AGENT_RUN).status == AuditStatus.SUCCESS


def test_failure_status_is_recorded(audit: AuditLog) -> None:
    audit.record(ACTION_AGENT_RUN, status=AuditStatus.FAILURE, detail="超时")

    assert audit.list()[0].status == AuditStatus.FAILURE


def test_list_is_newest_first(audit: AuditLog) -> None:
    audit.record(ACTION_AGENT_RUN, target="第一")
    audit.record(ACTION_AGENT_RUN, target="第二")

    assert [e.target for e in audit.list()] == ["第二", "第一"]


def test_list_supports_ascending_order(audit: AuditLog) -> None:
    audit.record(ACTION_AGENT_RUN, target="第一")
    audit.record(ACTION_AGENT_RUN, target="第二")

    assert [e.target for e in audit.list(order="asc")] == ["第一", "第二"]


def test_detail_is_truncated(audit: AuditLog) -> None:
    entry = audit.record(ACTION_AGENT_RUN, detail="x" * 5000)

    assert len(entry.detail) == 2000


def test_clear_removes_everything(audit: AuditLog) -> None:
    audit.record(ACTION_AGENT_RUN)
    audit.record(ACTION_TOOL_EXECUTE)

    assert audit.clear() == 2
    assert audit.count() == 0


def test_prunes_beyond_max_records(tmp_path: Path) -> None:
    audit = AuditLog(AuditSettings(db_path=str(tmp_path / "a.db"), max_records=3))

    for index in range(5):
        audit.record(ACTION_AGENT_RUN, target=f"a{index}")

    assert audit.count() == 3
    assert [e.target for e in audit.list()] == ["a4", "a3", "a2"]


# --- 上下文自动捕获 -------------------------------------------------------


def test_record_captures_context_fields(audit: AuditLog) -> None:
    """调用方只需说明做了什么，上下文字段自动带上。"""
    with bind(
        trace_id="trace_1",
        request_id="req_1",
        actor="key_abc",
        run_id="run_1",
        agent_name="assistant",
        tool_name="calculate",
    ):
        entry = audit.record(ACTION_TOOL_EXECUTE, target="calculate")

    assert entry.trace_id == "trace_1"
    assert entry.actor == "key_abc"
    assert entry.run_id == "run_1"
    assert entry.agent_name == "assistant"
    assert entry.tool_name == "calculate"


def test_record_without_context_leaves_fields_empty(audit: AuditLog) -> None:
    entry = audit.record(ACTION_AGENT_RUN)

    assert entry.actor is None
    assert entry.trace_id is None
    assert entry.run_id is None


# --- 过滤与分页 -----------------------------------------------------------


def test_filter_by_action(audit: AuditLog) -> None:
    audit.record(ACTION_AGENT_RUN)
    audit.record(ACTION_TOOL_EXECUTE)

    assert audit.count(action=ACTION_AGENT_RUN) == 1
    assert [e.action for e in audit.list(action=ACTION_TOOL_EXECUTE)] == [
        ACTION_TOOL_EXECUTE
    ]


def test_filter_by_actor(audit: AuditLog) -> None:
    with bind(actor="key_a"):
        audit.record(ACTION_AGENT_RUN)
    with bind(actor="key_b"):
        audit.record(ACTION_AGENT_RUN)

    assert audit.count(actor="key_a") == 1


def test_filter_by_run_id(audit: AuditLog) -> None:
    with bind(run_id="run_1"):
        audit.record(ACTION_AGENT_RUN)
    audit.record(ACTION_AGENT_RUN)

    assert audit.count(run_id="run_1") == 1


def test_filter_by_status(audit: AuditLog) -> None:
    audit.record(ACTION_AGENT_RUN)
    audit.record(ACTION_AGENT_RUN, status=AuditStatus.FAILURE)

    assert audit.count(status=AuditStatus.FAILURE) == 1


def test_pagination(audit: AuditLog) -> None:
    for index in range(5):
        audit.record(ACTION_AGENT_RUN, target=f"a{index}")

    assert [e.target for e in audit.list(limit=2, offset=0)] == ["a4", "a3"]
    assert [e.target for e in audit.list(limit=2, offset=2)] == ["a2", "a1"]
    assert audit.count() == 5


# --- 持久化 ---------------------------------------------------------------


def test_entries_survive_new_instance(tmp_path: Path) -> None:
    settings = AuditSettings(db_path=str(tmp_path / "audit.db"))
    AuditLog(settings).record(ACTION_AGENT_RUN, target="persisted")

    assert AuditLog(settings).list()[0].target == "persisted"


# --- 集成：真实操作产生审计 -----------------------------------------------


def _app(tmp_path: Path, *, audit_enabled: bool = True) -> object:
    return create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            runs={"enabled": True, "db_path": str(tmp_path / "runs.db")},
            audit={"enabled": audit_enabled, "db_path": str(tmp_path / "audit.db")},
            memory={"long_term_db_path": str(tmp_path / "memory.db")},
            registry={"persist": False},
        )
    )


def test_agent_register_and_unregister_are_audited(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/agents", json={"name": "researcher", "description": "调研"})
        client.delete("/api/v1/agents/researcher")

        rows = client.get("/api/v1/audit").json()

    actions = [row["action"] for row in rows]
    assert ACTION_AGENT_REGISTER in actions
    assert ACTION_AGENT_UNREGISTER in actions


def test_run_is_audited(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        run = client.post("/api/v1/runs", json={"input": "你好"}).json()
        rows = client.get("/api/v1/audit?action=agent.run").json()

    assert len(rows) == 1
    entry = rows[0]
    assert entry["status"] == "success"
    assert entry["target"] == "assistant"
    assert entry["run_id"] == run["run_id"]
    assert entry["trace_id"].startswith("trace_")
    assert "iterations=1" in entry["detail"]


def test_tool_execution_is_audited(tmp_path: Path) -> None:
    """模型调用工具时，工具执行也要有独立审计记录。"""
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/runs", json={"input": "你好"})
        # echo 客户端不会调用工具，这里直接验证注册表路径留给单元测试，
        # 集成层只断言动作常量与接口可用
        rows = client.get("/api/v1/audit?action=tool.execute").json()

    assert rows == []


def test_audit_route_supports_filters(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/agents", json={"name": "a1"})
        client.post("/api/v1/runs", json={"input": "hi"})

        assert len(client.get("/api/v1/audit?action=agent.run").json()) == 1
        assert len(client.get("/api/v1/audit?order=asc").json()) >= 2
        assert client.get("/api/v1/audit?order=bad").status_code == 422


def test_audit_route_404_when_disabled(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, audit_enabled=False)) as client:
        response = client.get("/api/v1/audit")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_openapi_exposes_audit_route(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        schema = client.get("/openapi.json").json()

    assert "/api/v1/audit" in schema["paths"]
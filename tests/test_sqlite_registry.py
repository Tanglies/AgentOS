"""Agent 注册表持久化测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.core.config import RuntimeSettings, Settings
from agentos.core.exceptions import ConflictError, NotFoundError
from agentos.runtime import (
    Agent,
    AgentRegistry,
    SQLiteAgentRegistry,
    build_registry,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "agents.db")


# --- 存储基础 -------------------------------------------------------------


def test_register_and_get(db_path: str) -> None:
    registry = SQLiteAgentRegistry(db_path)

    registry.register(Agent(name="researcher", description="调研专家"))

    agent = registry.get("researcher")
    assert agent.name == "researcher"
    assert agent.description == "调研专家"


def test_list_is_sorted_by_name(db_path: str) -> None:
    registry = SQLiteAgentRegistry(db_path)
    registry.register(Agent(name="zeta"))
    registry.register(Agent(name="alpha"))

    assert [agent.name for agent in registry.list()] == ["alpha", "zeta"]


def test_duplicate_registration_conflicts(db_path: str) -> None:
    registry = SQLiteAgentRegistry(db_path)
    registry.register(Agent(name="dup"))

    with pytest.raises(ConflictError):
        registry.register(Agent(name="dup"))


def test_overwrite_replaces_payload(db_path: str) -> None:
    registry = SQLiteAgentRegistry(db_path)
    registry.register(Agent(name="item", description="旧"))
    registry.register(Agent(name="item", description="新"), overwrite=True)

    assert registry.get("item").description == "新"
    assert len(registry) == 1


def test_unregister_removes_agent(db_path: str) -> None:
    registry = SQLiteAgentRegistry(db_path)
    registry.register(Agent(name="temp"))

    registry.unregister("temp")

    assert len(registry) == 0
    with pytest.raises(NotFoundError):
        registry.unregister("temp")


def test_get_unknown_lists_available_names(db_path: str) -> None:
    registry = SQLiteAgentRegistry(db_path)
    registry.register(Agent(name="alpha"))
    registry.register(Agent(name="beta"))

    with pytest.raises(NotFoundError) as excinfo:
        registry.get("ghost")

    assert excinfo.value.details["available"] == ["alpha", "beta"]


def test_contains_and_len(db_path: str) -> None:
    registry = SQLiteAgentRegistry(db_path)
    registry.register(Agent(name="alpha"))

    assert "alpha" in registry
    assert "ghost" not in registry
    assert 123 not in registry
    assert len(registry) == 1


def test_constructor_seeds_initial_agents(db_path: str) -> None:
    SQLiteAgentRegistry(db_path, [Agent(name="seeded")])

    assert "seeded" in SQLiteAgentRegistry(db_path)


# --- 持久化（核心价值）----------------------------------------------------


def test_agents_survive_new_instance(db_path: str) -> None:
    first = SQLiteAgentRegistry(db_path)
    first.register(Agent(name="researcher", description="调研专家", tools=["read_file"]))

    # 模拟进程重启：新实例读同一个文件
    second = SQLiteAgentRegistry(db_path)

    agent = second.get("researcher")
    assert agent.description == "调研专家"
    assert agent.tools == ["read_file"]


def test_complex_fields_round_trip(db_path: str) -> None:
    registry = SQLiteAgentRegistry(db_path)
    original = Agent(
        name="complex",
        system_prompt="你是助手",
        model="qwen3.8-max",
        temperature=0.3,
        max_iterations=5,
        tools=["calculate", "read_file"],
        metadata={"team": "data", "level": 3},
    )

    registry.register(original)
    restored = SQLiteAgentRegistry(db_path).get("complex")

    assert restored.model_dump() == original.model_dump()


def test_database_file_is_created(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "agents.db"
    SQLiteAgentRegistry(str(path))

    assert path.exists()


# --- build_registry -------------------------------------------------------


def test_build_registry_without_path_uses_memory() -> None:
    registry = build_registry(RuntimeSettings())

    assert isinstance(registry, AgentRegistry)
    assert not isinstance(registry, SQLiteAgentRegistry)


def test_build_registry_with_path_uses_sqlite(db_path: str) -> None:
    registry = build_registry(RuntimeSettings(), persist_path=db_path)

    assert isinstance(registry, SQLiteAgentRegistry)


def test_build_registry_seeds_default_agent(db_path: str) -> None:
    registry = build_registry(RuntimeSettings(default_agent="assistant"), persist_path=db_path)

    assert "assistant" in registry


def test_build_registry_does_not_overwrite_existing_default(db_path: str) -> None:
    seeded = SQLiteAgentRegistry(db_path)
    seeded.register(
        Agent(name="assistant", description="我改过的", system_prompt="自定义")
    )

    registry = build_registry(RuntimeSettings(), persist_path=db_path)

    assert registry.get("assistant").description == "我改过的"


def test_build_registry_seeds_with_current_tools(db_path: str) -> None:
    registry = build_registry(
        RuntimeSettings(), tools=["calculate", "read_file"], persist_path=db_path
    )

    assert registry.get("assistant").tools == ["calculate", "read_file"]


# --- API 端到端 -----------------------------------------------------------


def _app(tmp_path: Path, *, persist: bool) -> object:
    return create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            registry={"persist": persist, "db_path": str(tmp_path / "agents.db")},
            memory={"long_term_db_path": str(tmp_path / "memory.db")},
        )
    )


def test_api_agents_persist_across_app_restarts(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, persist=True)) as client:
        client.post("/api/v1/agents", json={"name": "researcher", "description": "调研专家"})

    # 重新建 app 模拟进程重启
    with TestClient(_app(tmp_path, persist=True)) as client:
        names = [item["name"] for item in client.get("/api/v1/agents").json()["items"]]

    assert "researcher" in names
    assert "assistant" in names


def test_api_without_persistence_loses_agents(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, persist=False)) as client:
        client.post("/api/v1/agents", json={"name": "ephemeral"})

    with TestClient(_app(tmp_path, persist=False)) as client:
        names = [item["name"] for item in client.get("/api/v1/agents").json()["items"]]

    assert "ephemeral" not in names


def test_api_delete_survives_restart(tmp_path: Path) -> None:
    """删除也要持久化，否则重启后「删除的 Agent」会复活。"""
    with TestClient(_app(tmp_path, persist=True)) as client:
        client.post("/api/v1/agents", json={"name": "doomed"})
        assert client.delete("/api/v1/agents/doomed").status_code == 204

    with TestClient(_app(tmp_path, persist=True)) as client:
        names = [item["name"] for item in client.get("/api/v1/agents").json()["items"]]

    assert "doomed" not in names


def test_api_default_agent_still_has_tools(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, persist=True)) as client:
        agent = client.get("/api/v1/agents/assistant").json()

    assert "delegate_to_agent" in agent["tools"]
    assert "calculate" in agent["tools"]
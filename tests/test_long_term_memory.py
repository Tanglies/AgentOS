"""长期记忆测试：SQLite 持久化、关键词检索、工具与 API。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentos.core.config import MemorySettings, Settings
from agentos.llm import EchoLLMClient
from agentos.llm.base import ToolCall
from agentos.runtime import Agent, AgentRuntime, LongTermMemory, ToolRegistry
from agentos.runtime.long_term_memory import extract_terms
from agentos.runtime.memory_tools import create_memory_tools


@pytest.fixture
def memory(tmp_path: Path) -> LongTermMemory:
    return LongTermMemory(MemorySettings(long_term_db_path=str(tmp_path / "memory.db")))


# --- 检索词抽取 -----------------------------------------------------------


def test_extract_terms_keeps_ascii_words() -> None:
    assert extract_terms("AgentOS FastAPI") == ["agentos", "fastapi"]


def test_extract_terms_expands_cjk_bigrams() -> None:
    terms = extract_terms("数据分析师")

    assert "数据分析师" in terms
    assert "数据" in terms
    assert "分析" in terms


def test_extract_terms_keeps_short_cjk_run() -> None:
    assert extract_terms("周明") == ["周明"]


def test_extract_terms_ignores_single_characters() -> None:
    assert extract_terms("a 的 b") == []


# --- 存储 -----------------------------------------------------------------


def test_remember_and_count(memory: LongTermMemory) -> None:
    record = memory.remember("用户偏好中文回答")

    assert record.id > 0
    assert record.content == "用户偏好中文回答"
    assert memory.count() == 1


def test_remember_strips_and_rejects_empty(memory: LongTermMemory) -> None:
    assert memory.remember("  有内容  ").content == "有内容"

    with pytest.raises(ValueError):
        memory.remember("   ")


def test_remember_truncates_long_content(memory: LongTermMemory) -> None:
    record = memory.remember("x" * 5000)

    assert len(record.content) == 4000


def test_list_returns_newest_first(memory: LongTermMemory) -> None:
    memory.remember("第一条")
    memory.remember("第二条")

    assert [record.content for record in memory.list()] == ["第二条", "第一条"]


def test_forget_reports_whether_record_existed(memory: LongTermMemory) -> None:
    record = memory.remember("待删除")

    assert memory.forget(record.id) is True
    assert memory.forget(record.id) is False
    assert memory.count() == 0


def test_clear_removes_everything(memory: LongTermMemory) -> None:
    memory.remember("a")
    memory.remember("b")

    assert memory.clear() == 2
    assert memory.count() == 0


# --- 持久化（长期记忆的核心价值）-------------------------------------------


def test_memory_survives_new_instance(tmp_path: Path) -> None:
    settings = MemorySettings(long_term_db_path=str(tmp_path / "memory.db"))
    first = LongTermMemory(settings)
    first.remember("用户叫周明")

    # 模拟进程重启：新实例读同一个文件
    second = LongTermMemory(settings)

    assert second.count() == 1
    assert second.recall("周明")[0].content == "用户叫周明"


def test_database_file_is_created(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "memory.db"
    LongTermMemory(MemorySettings(long_term_db_path=str(db_path)))

    assert db_path.exists()


# --- 检索 -----------------------------------------------------------------


def test_recall_matches_short_cjk_query(memory: LongTermMemory) -> None:
    """两个字的中文词也要能召回（FTS5 默认分词器做不到）。"""
    memory.remember("用户叫周明，是一名数据分析师")

    assert len(memory.recall("周明")) == 1


def test_recall_matches_ascii_query(memory: LongTermMemory) -> None:
    memory.remember("当前项目使用 FastAPI 和 SQLite")

    assert len(memory.recall("fastapi")) == 1


def test_recall_returns_empty_for_unrelated_query(memory: LongTermMemory) -> None:
    memory.remember("用户叫周明")

    assert memory.recall("今天天气怎么样") == []


def test_recall_respects_limit(memory: LongTermMemory) -> None:
    for index in range(5):
        memory.remember(f"用户偏好中文回答 第{index}条")

    assert len(memory.recall("中文", limit=2)) == 2


def test_recall_ranks_longer_match_first(memory: LongTermMemory) -> None:
    memory.remember("数据分析")
    memory.remember("数据分析师")

    hits = memory.recall("数据分析师")

    assert hits[0].content == "数据分析师"


def test_recall_on_empty_query_returns_nothing(memory: LongTermMemory) -> None:
    memory.remember("用户叫周明")

    assert memory.recall("   ") == []


# --- 工具 -----------------------------------------------------------------


def test_create_memory_tools_exposes_remember_and_recall(
    memory: LongTermMemory,
) -> None:
    names = [tool.name for tool in create_memory_tools(memory)]

    assert names == ["remember", "recall"]


async def test_remember_tool_writes_record(memory: LongTermMemory) -> None:
    registry = ToolRegistry(create_memory_tools(memory))

    result = await registry.execute(
        ToolCall(id="c1", name="remember", arguments='{"content": "用户偏好中文回答"}')
    )

    assert result.is_error is False
    assert "已写入长期记忆" in result.content
    assert memory.count() == 1


async def test_recall_tool_returns_matches(memory: LongTermMemory) -> None:
    memory.remember("用户叫周明")
    registry = ToolRegistry(create_memory_tools(memory))

    result = await registry.execute(
        ToolCall(id="c1", name="recall", arguments='{"query": "周明"}')
    )

    assert "用户叫周明" in result.content


async def test_recall_tool_reports_no_match(memory: LongTermMemory) -> None:
    registry = ToolRegistry(create_memory_tools(memory))

    result = await registry.execute(
        ToolCall(id="c1", name="recall", arguments='{"query": "不存在"}')
    )

    assert "没有找到" in result.content


# --- Runtime 自动召回 ------------------------------------------------------


async def test_runtime_injects_recalled_memory(tmp_path: Path) -> None:
    memory = LongTermMemory(
        MemorySettings(long_term_db_path=str(tmp_path / "memory.db"))
    )
    memory.remember("用户叫周明，是一名数据分析师")
    runtime = AgentRuntime(EchoLLMClient(), long_term=memory)
    agent = Agent(name="chat", system_prompt="be nice")

    result = await runtime.run(agent, "数据分析师日常做什么？")

    system_message = result.messages[0]
    assert system_message.role.value == "system"
    assert "be nice" in system_message.content
    assert "[长期记忆]" in system_message.content
    assert "用户叫周明" in system_message.content


async def test_runtime_injects_system_message_when_agent_has_no_prompt(
    tmp_path: Path,
) -> None:
    memory = LongTermMemory(
        MemorySettings(long_term_db_path=str(tmp_path / "memory.db"))
    )
    memory.remember("用户叫周明")
    runtime = AgentRuntime(EchoLLMClient(), long_term=memory)

    result = await runtime.run(Agent(name="chat"), "周明是谁？")

    assert result.messages[0].role.value == "system"
    assert "[长期记忆]" in result.messages[0].content


async def test_runtime_skips_injection_when_disabled(tmp_path: Path) -> None:
    settings = MemorySettings(
        long_term_db_path=str(tmp_path / "memory.db"), long_term_auto_recall=False
    )
    memory = LongTermMemory(settings)
    memory.remember("用户叫周明")
    runtime = AgentRuntime(EchoLLMClient(), long_term=memory)

    result = await runtime.run(Agent(name="chat", system_prompt="be nice"), "周明是谁？")

    assert "[长期记忆]" not in result.messages[0].content


async def test_runtime_without_long_term_memory_has_no_injection() -> None:
    runtime = AgentRuntime(EchoLLMClient())

    result = await runtime.run(Agent(name="chat", system_prompt="be nice"), "你好")

    assert "[长期记忆]" not in result.messages[0].content


# --- API ------------------------------------------------------------------


def test_memory_crud_over_api(client: TestClient) -> None:
    assert client.get("/api/v1/memories").json()["total"] == 0

    created = client.post("/api/v1/memories", json={"content": "用户叫周明"})
    assert created.status_code == 201
    memory_id = created.json()["id"]

    listing = client.get("/api/v1/memories").json()
    assert listing["total"] == 1
    assert listing["items"][0]["content"] == "用户叫周明"

    assert client.delete(f"/api/v1/memories/{memory_id}").status_code == 204
    assert client.get("/api/v1/memories").json()["total"] == 0


def test_delete_unknown_memory_returns_404(client: TestClient) -> None:
    response = client.delete("/api/v1/memories/9999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_create_memory_rejects_empty_content(client: TestClient) -> None:
    assert client.post("/api/v1/memories", json={"content": ""}).status_code == 422


def test_memory_tools_are_registered(client: TestClient) -> None:
    names = {item["name"] for item in client.get("/api/v1/tools").json()["items"]}

    assert {"remember", "recall"} <= names


def test_run_uses_long_term_memory_over_api(client: TestClient) -> None:
    client.post("/api/v1/memories", json={"content": "用户叫周明，是数据分析师"})

    body = client.post("/api/v1/runs", json={"input": "周明做什么工作？"}).json()

    assert "[长期记忆]" in body["messages"][0]["content"]


def test_openapi_exposes_memories_route(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/memories" in schema["paths"]
    assert "/api/v1/memories/{memory_id}" in schema["paths"]


def test_memories_route_returns_404_when_disabled(tmp_path: Path) -> None:
    from agentos.api.app import create_app

    settings = Settings(
        _env_file=None,
        llm={"provider": "echo"},
        logging={"level": "WARNING"},
        memory={
            "long_term_enabled": False,
            "long_term_db_path": str(tmp_path / "memory.db"),
        },
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/memories").status_code == 404
        names = {item["name"] for item in client.get("/api/v1/tools").json()["items"]}
        assert "remember" not in names
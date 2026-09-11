"""会话记忆测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentos.core.config import MemorySettings, RuntimeSettings
from agentos.llm import EchoLLMClient
from agentos.runtime import Agent, AgentRuntime, MemoryStore, Message


def _messages(count: int) -> list[Message]:
    result: list[Message] = []
    for index in range(1, count + 1):
        result.append(Message.user(f"u{index}"))
        result.append(Message.assistant(f"a{index}"))
    return result


# --- MemoryStore ----------------------------------------------------------


def test_memory_returns_empty_history_for_unknown_session() -> None:
    store = MemoryStore()

    assert store.history("missing") == []
    assert store.get("missing") is None
    assert "missing" not in store


def test_memory_new_session_id_has_prefix() -> None:
    assert MemoryStore.new_session_id().startswith("sess_")


def test_memory_appends_and_reads_history() -> None:
    store = MemoryStore()

    store.append("s1", _messages(1))

    assert [message.content for message in store.history("s1")] == ["u1", "a1"]
    assert len(store) == 1
    assert "s1" in store


def test_memory_counts_user_turns() -> None:
    store = MemoryStore()

    store.append("s1", _messages(3))

    state = store.get("s1")
    assert state is not None
    assert state.turn_count == 3


def test_memory_truncates_to_recent_turns() -> None:
    store = MemoryStore(MemorySettings(max_messages_per_session=4))

    store.append("s1", _messages(4))

    # 只保留最近 4 条，且从 user 开始对齐
    assert [message.content for message in store.history("s1")] == ["u3", "a3", "u4", "a4"]


def test_memory_truncation_does_not_break_tool_pairs() -> None:
    store = MemoryStore(MemorySettings(max_messages_per_session=3))
    store.append(
        "s1",
        [
            Message.user("u1"),
            Message.assistant("a1"),
            Message.user("u2"),
            Message.assistant("a2"),
        ],
    )

    messages = store.history("s1")

    assert messages[0].role.value == "user"
    assert len(messages) <= 3


def test_memory_evicts_least_recently_used_session() -> None:
    store = MemoryStore(MemorySettings(max_sessions=2))

    store.append("s1", _messages(1))
    store.append("s2", _messages(1))
    store.append("s3", _messages(1))

    assert len(store) == 2
    assert "s1" not in store
    assert "s2" in store
    assert "s3" in store


def test_memory_access_refreshes_lru_order() -> None:
    store = MemoryStore(MemorySettings(max_sessions=2))
    store.append("s1", _messages(1))
    store.append("s2", _messages(1))

    # 访问 s1 使其成为最近使用
    store.get("s1")
    store.append("s3", _messages(1))

    assert "s1" in store
    assert "s2" not in store


def test_memory_list_returns_most_recent_first() -> None:
    store = MemoryStore()
    store.append("s1", _messages(1))
    store.append("s2", _messages(1))

    assert [state.session_id for state in store.list()] == ["s2", "s1"]


def test_memory_clear_reports_whether_session_existed() -> None:
    store = MemoryStore()
    store.append("s1", _messages(1))

    assert store.clear("s1") is True
    assert store.clear("s1") is False
    assert len(store) == 0


# --- Runtime 集成 ---------------------------------------------------------


async def test_runtime_reuses_session_history() -> None:
    runtime = AgentRuntime(EchoLLMClient())
    agent = Agent(name="chat", system_prompt="be nice")

    await runtime.run(agent, "我叫小明", session_id="demo")
    second = await runtime.run(agent, "我叫什么", session_id="demo")

    contents = [message.content for message in second.messages]
    # 第一轮只应出现一次，不能重复追加
    assert contents.count("我叫小明") == 1
    assert contents == [
        "be nice",
        "我叫小明",
        "Echo: 我叫小明",
        "我叫什么",
        "Echo: 我叫什么",
    ]
    assert second.session_id == "demo"


async def test_runtime_session_history_is_not_persisted_in_messages() -> None:
    """系统提示词不应被写进会话记忆。"""
    runtime = AgentRuntime(EchoLLMClient())
    agent = Agent(name="chat", system_prompt="be nice")

    await runtime.run(agent, "hi", session_id="demo")

    stored = runtime.memory.history("demo")
    assert [message.role.value for message in stored] == ["user", "assistant"]


async def test_runtime_without_session_id_uses_default_session() -> None:
    """记忆开箱即用：不传 session_id 时落到配置的默认会话。"""
    runtime = AgentRuntime(EchoLLMClient())
    agent = Agent(name="chat", system_prompt="be nice")

    first = await runtime.run(agent, "我叫小明")
    second = await runtime.run(agent, "我叫什么")

    assert first.session_id == "default"
    assert second.session_id == "default"
    assert len(runtime.memory) == 1
    assert any(message.content == "我叫小明" for message in second.messages)


async def test_runtime_default_session_can_be_disabled() -> None:
    """把默认会话设为空字符串即可恢复无状态行为。"""
    memory = MemoryStore(MemorySettings(default_session_id=""))
    runtime = AgentRuntime(EchoLLMClient(), memory=memory)

    result = await runtime.run(Agent(name="chat"), "hi")

    assert result.session_id is None
    assert len(memory) == 0


async def test_runtime_explicit_history_takes_precedence_over_default_session() -> None:
    """显式传 history 时以调用方为准，不读写默认会话。"""
    runtime = AgentRuntime(EchoLLMClient())

    result = await runtime.run(
        Agent(name="chat"), "第二句", history=[Message.user("第一句")]
    )

    assert result.session_id is None
    assert [message.content for message in result.messages] == [
        "第一句",
        "第二句",
        "Echo: 第二句",
    ]
    assert len(runtime.memory) == 0


async def test_runtime_session_id_ignores_explicit_history() -> None:
    runtime = AgentRuntime(EchoLLMClient())
    agent = Agent(name="chat")
    await runtime.run(agent, "第一句", session_id="demo")

    result = await runtime.run(
        agent,
        "第二句",
        history=[Message.user("不该出现的历史")],
        session_id="demo",
    )

    contents = [message.content for message in result.messages]
    assert "不该出现的历史" not in contents
    assert "第一句" in contents


async def test_runtime_respects_memory_settings_truncation() -> None:
    runtime = AgentRuntime(
        EchoLLMClient(), memory=MemoryStore(MemorySettings(max_messages_per_session=2))
    )
    agent = Agent(name="chat")

    for index in range(1, 4):
        await runtime.run(agent, f"第{index}句", session_id="demo")

    stored = runtime.memory.history("demo")
    assert [message.content for message in stored] == ["第3句", "Echo: 第3句"]


# --- API ------------------------------------------------------------------


def test_run_accepts_session_id(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runs", json={"input": "我叫小明", "session_id": "chat-1"}
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "chat-1"


def test_run_without_session_id_falls_back_to_default(client: TestClient) -> None:
    body = client.post("/api/v1/runs", json={"input": "hi"}).json()

    assert body["session_id"] == "default"


def test_run_without_session_id_remembers_across_calls(client: TestClient) -> None:
    client.post("/api/v1/runs", json={"input": "我叫小明"})
    second = client.post("/api/v1/runs", json={"input": "我叫什么"}).json()

    assert any(message["content"] == "我叫小明" for message in second["messages"])


def test_session_round_trip_over_api(client: TestClient) -> None:
    client.post("/api/v1/runs", json={"input": "第一句", "session_id": "chat-1"})
    second = client.post(
        "/api/v1/runs", json={"input": "第二句", "session_id": "chat-1"}
    ).json()

    contents = [message["content"] for message in second["messages"]]
    assert contents.count("第一句") == 1
    assert len(second["messages"]) == 5


def test_list_sessions_reports_turns(client: TestClient) -> None:
    client.post("/api/v1/runs", json={"input": "hi", "session_id": "chat-1"})

    body = client.get("/api/v1/sessions").json()

    assert body["total"] == 1
    assert body["items"][0]["session_id"] == "chat-1"
    assert body["items"][0]["turns"] == 1


def test_get_session_detail(client: TestClient) -> None:
    client.post("/api/v1/runs", json={"input": "hi", "session_id": "chat-1"})

    body = client.get("/api/v1/sessions/chat-1").json()

    assert body["session_id"] == "chat-1"
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]


def test_get_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/sessions/ghost")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_delete_session_clears_memory(client: TestClient) -> None:
    client.post("/api/v1/runs", json={"input": "hi", "session_id": "chat-1"})

    assert client.delete("/api/v1/sessions/chat-1").status_code == 204
    assert client.get("/api/v1/sessions/chat-1").status_code == 404

    # 清空后重新开始，历史不应残留
    body = client.post(
        "/api/v1/runs", json={"input": "新对话", "session_id": "chat-1"}
    ).json()
    assert [message["role"] for message in body["messages"]] == [
        "system",
        "user",
        "assistant",
    ]


def test_delete_unknown_session_returns_404(client: TestClient) -> None:
    assert client.delete("/api/v1/sessions/ghost").status_code == 404


def test_openapi_exposes_sessions_route(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/sessions" in schema["paths"]
    assert "/api/v1/sessions/{session_id}" in schema["paths"]


def test_runtime_settings_fixture_is_independent() -> None:
    """确保默认 RuntimeSettings 不受测试夹具影响。"""
    assert RuntimeSettings().max_iterations == 8
"""运行记录持久化与历史查询测试。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.core.config import RunStoreSettings, RuntimeSettings, Settings
from agentos.core.exceptions import AgentRuntimeError, NotFoundError
from agentos.llm import EchoLLMClient
from agentos.llm.base import LLMResponse, TokenUsage
from agentos.runtime import Agent, AgentRuntime
from agentos.runtime.message import Message
from agentos.runtime.run_store import RunStatus, RunStore
from agentos.runtime.runtime import RunResult


def _result(run_id: str = "run_1", **overrides: object) -> RunResult:
    payload: dict[str, object] = {
        "run_id": run_id,
        "agent": "assistant",
        "output": "回答",
        "messages": [Message.user("问题"), Message.assistant("回答")],
        "usage": TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        "iterations": 1,
        "duration_ms": 12.5,
        "finish_reason": "stop",
        "tool_call_count": 0,
        "session_id": "default",
    }
    payload.update(overrides)
    return RunResult.model_validate(payload)


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(RunStoreSettings(db_path=str(tmp_path / "runs.db")))


# --- 存储基础 -------------------------------------------------------------


def test_record_and_get(store: RunStore) -> None:
    store.record(_result("run_a"), input_text="你好")

    record = store.get("run_a")
    assert record.run_id == "run_a"
    assert record.input == "你好"
    assert record.output == "回答"
    assert record.status == RunStatus.COMPLETED
    assert record.total_tokens == 5


def test_get_unknown_raises(store: RunStore) -> None:
    with pytest.raises(NotFoundError):
        store.get("ghost")


def test_record_failure_marks_status(store: RunStore) -> None:
    store.record_failure(
        run_id="run_fail", agent="assistant", input_text="触发错误", error="boom"
    )

    record = store.get("run_fail")
    assert record.status == RunStatus.FAILED
    assert record.error == "boom"
    assert record.output == ""


def test_list_returns_newest_first(store: RunStore) -> None:
    store.record(_result("run_1"), input_text="第一")
    store.record(_result("run_2"), input_text="第二")

    assert [record.run_id for record in store.list()] == ["run_2", "run_1"]


def test_list_omits_messages_but_detail_keeps_them(store: RunStore) -> None:
    store.record(_result("run_a"), input_text="你好")

    assert store.list()[0].messages == []
    assert len(store.get("run_a").messages) == 2


def test_count_and_clear(store: RunStore) -> None:
    store.record(_result("run_1"))
    store.record(_result("run_2"))

    assert store.count() == 2
    assert store.clear() == 2
    assert store.count() == 0


def test_input_is_truncated(store: RunStore) -> None:
    store.record(_result("run_long"), input_text="x" * 9000)

    assert len(store.get("run_long").input) == 4000


# --- 容量淘汰 -------------------------------------------------------------


def test_prunes_oldest_records(tmp_path: Path) -> None:
    store = RunStore(RunStoreSettings(db_path=str(tmp_path / "runs.db"), max_records=3))

    for index in range(5):
        store.record(_result(f"run_{index}"))

    assert store.count() == 3
    remaining = {record.run_id for record in store.list()}
    assert remaining == {"run_2", "run_3", "run_4"}


# --- 过滤与分页 -----------------------------------------------------------


def test_filter_by_agent(store: RunStore) -> None:
    store.record(_result("run_1", agent="assistant"))
    store.record(_result("run_2", agent="researcher"))

    assert store.count(agent="researcher") == 1
    assert [r.run_id for r in store.list(agent="researcher")] == ["run_2"]


def test_filter_by_session(store: RunStore) -> None:
    store.record(_result("run_1", session_id="s-1"))
    store.record(_result("run_2", session_id="s-2"))

    assert store.count(session_id="s-1") == 1


def test_filter_by_status(store: RunStore) -> None:
    store.record(_result("run_ok"))
    store.record_failure(run_id="run_bad", agent="assistant", input_text="x", error="e")

    assert store.count(status=RunStatus.COMPLETED) == 1
    assert store.count(status=RunStatus.FAILED) == 1


def test_pagination_with_limit_and_offset(store: RunStore) -> None:
    for index in range(5):
        store.record(_result(f"run_{index}"))

    first_page = store.list(limit=2, offset=0)
    second_page = store.list(limit=2, offset=2)

    assert [r.run_id for r in first_page] == ["run_4", "run_3"]
    assert [r.run_id for r in second_page] == ["run_2", "run_1"]
    # total 是满足条件的总数，不受分页影响
    assert store.count() == 5


# --- 持久化 ---------------------------------------------------------------


def test_store_recovers_when_directory_is_removed(tmp_path: Path) -> None:
    """目录被外部删掉（例如用户手工清空 .agentos/）后应能自动重建。"""
    db = tmp_path / "data" / "runs.db"
    store = RunStore(RunStoreSettings(db_path=str(db)))
    store.record(_result("run_1"))
    assert store.count() == 1

    shutil.rmtree(tmp_path / "data")

    store.record(_result("run_2"))
    assert store.count() == 1
    assert store.get("run_2").run_id == "run_2"


def test_store_recovers_when_db_file_is_removed(tmp_path: Path) -> None:
    """只删数据库文件时，表结构应自动重建，而不是抛 no such table。"""
    db = tmp_path / "runs.db"
    store = RunStore(RunStoreSettings(db_path=str(db)))
    store.record(_result("run_1"))

    db.unlink()

    assert store.count() == 0
    store.record(_result("run_2"))
    assert store.count() == 1


def test_records_survive_new_instance(tmp_path: Path) -> None:
    settings = RunStoreSettings(db_path=str(tmp_path / "runs.db"))
    RunStore(settings).record(_result("run_persist"), input_text="跨重启")

    reopened = RunStore(settings)

    assert reopened.count() == 1
    assert reopened.get("run_persist").input == "跨重启"


# --- Runtime 集成 ---------------------------------------------------------


async def test_successful_run_is_recorded(tmp_path: Path) -> None:
    store = RunStore(RunStoreSettings(db_path=str(tmp_path / "runs.db")))
    runtime = AgentRuntime(EchoLLMClient(), runs=store)

    result = await runtime.run(Agent(name="chat", system_prompt="x"), "你好")

    record = store.get(result.run_id)
    assert record.status == RunStatus.COMPLETED
    assert record.input == "你好"
    assert record.output == "Echo: 你好"
    assert record.total_tokens > 0


async def test_failed_run_is_recorded(tmp_path: Path) -> None:
    """失败同样要留痕，否则排查时只能翻日志。"""
    from collections.abc import AsyncIterator, Sequence

    from agentos.llm.base import CompletionOptions, LLMMessage, StreamChunk, ToolCall

    class LoopingClient(EchoLLMClient):
        """每轮都要求调用工具，配合 max_iterations=1 必然失败。"""

        async def complete(
            self,
            messages: Sequence[LLMMessage],
            *,
            options: CompletionOptions | None = None,
        ) -> LLMResponse:  # pragma: no cover - 仅满足抽象方法
            raise NotImplementedError

        async def stream(
            self,
            messages: Sequence[LLMMessage],
            *,
            options: CompletionOptions | None = None,
        ) -> AsyncIterator[StreamChunk]:
            yield StreamChunk(
                tool_calls=[
                    ToolCall(id="c", name="calculate", arguments='{"expression": "1+1"}')
                ],
                finish_reason="tool_calls",
            )

    store = RunStore(RunStoreSettings(db_path=str(tmp_path / "runs.db")))
    runtime = AgentRuntime(
        LoopingClient(), runs=store, settings=RuntimeSettings(max_iterations=1)
    )

    with pytest.raises(AgentRuntimeError):
        await runtime.run(Agent(name="loop", tools=["calculate"]), "循环")

    records = store.list(status=RunStatus.FAILED)
    assert len(records) == 1
    assert records[0].agent == "loop"
    assert "max_iterations" in (records[0].error or "")


async def test_runtime_without_store_does_not_record() -> None:
    runtime = AgentRuntime(EchoLLMClient())

    assert runtime.runs is None
    await runtime.run(Agent(name="chat"), "你好")  # 不应报错


# --- API ------------------------------------------------------------------


def _app(tmp_path: Path, *, enabled: bool = True) -> object:
    return create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            runs={"enabled": enabled, "db_path": str(tmp_path / "runs.db")},
            memory={"long_term_db_path": str(tmp_path / "memory.db")},
        )
    )


def test_api_lists_run_history(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        first = client.post("/api/v1/runs", json={"input": "第一个"}).json()
        client.post("/api/v1/runs", json={"input": "第二个", "session_id": "s-1"})

        body = client.get("/api/v1/runs").json()

    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["run_id"] != first["run_id"]  # 最新在前


def test_api_run_detail_includes_messages(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        run_id = client.post("/api/v1/runs", json={"input": "你好"}).json()["run_id"]

        detail = client.get(f"/api/v1/runs/{run_id}").json()

    assert detail["run_id"] == run_id
    assert detail["status"] == "completed"
    assert [m["role"] for m in detail["messages"]] == ["system", "user", "assistant"]


def test_api_filters_and_pagination(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/runs", json={"input": "a"})
        client.post("/api/v1/runs", json={"input": "b", "session_id": "s-1"})

        assert client.get("/api/v1/runs?session_id=s-1").json()["total"] == 1
        assert client.get("/api/v1/runs?status=completed").json()["total"] == 2
        assert client.get("/api/v1/runs?status=failed").json()["total"] == 0
        assert len(client.get("/api/v1/runs?limit=1").json()["items"]) == 1
        assert client.get("/api/v1/runs?limit=1").json()["limit"] == 1


def test_api_unknown_run_returns_404(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/v1/runs/ghost")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_api_history_disabled_returns_404(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, enabled=False)) as client:
        assert client.get("/api/v1/runs").status_code == 404
        # 执行本身仍然可用，只是不落盘
        assert client.post("/api/v1/runs", json={"input": "hi"}).status_code == 200


def test_openapi_exposes_run_history_routes(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        schema = client.get("/openapi.json").json()

    assert "/api/v1/runs/{run_id}" in schema["paths"]
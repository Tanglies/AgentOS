"""Streaming cancellation propagation tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest

from agentos.core.config import ObservabilitySettings, RunStoreSettings
from agentos.llm.base import CompletionOptions, LLMClient, LLMMessage, LLMResponse, StreamChunk
from agentos.observability.metrics import configure_metrics, render_metrics
from agentos.runtime.agent import Agent
from agentos.runtime.run_store import RunStatus, RunStore
from agentos.runtime.runtime import AgentRuntime


class _CancelAwareClient(LLMClient):
    provider = "cancel-aware"

    def __init__(self) -> None:
        self.cancelled = False
        self.started = asyncio.Event()

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        self.started.set()
        try:
            yield StreamChunk(delta="partial")
            await asyncio.sleep(60)
        finally:
            self.cancelled = True


@pytest.mark.asyncio
async def test_cancelled_stream_propagates_and_records_status(tmp_path) -> None:
    client = _CancelAwareClient()
    store = RunStore(RunStoreSettings(db_path=str(tmp_path / "runs.db")))
    runtime = AgentRuntime(client, runs=store)
    configure_metrics(ObservabilitySettings(prometheus_enabled=True))

    async def consume() -> None:
        async for _event in runtime.run_stream(Agent(name="chat"), "hello"):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(client.started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.cancelled is True
    records = store.list(status=RunStatus.CANCELLED)
    assert len(records) == 1
    assert records[0].status == RunStatus.CANCELLED
    assert b'agentos_runs_total' in render_metrics()
    assert b'status="cancelled"' in render_metrics()
    await runtime.aclose()

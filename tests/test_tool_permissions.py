"""Workspace/Agent Tool visibility and execution checks."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentos.core.config import PlatformSettings, ToolsSettings
from agentos.core.context import bind
from agentos.llm.base import CompletionOptions, LLMMessage, StreamChunk, ToolCall
from agentos.llm.echo import EchoLLMClient
from agentos.runtime.agent import Agent
from agentos.runtime.builtin_tools import create_default_tool_registry
from agentos.runtime.platform_store import PlatformStore
from agentos.runtime.runtime import AgentRuntime
from agentos.runtime.services.tool_policy_service import ToolPolicyService
from tenancy_support import create_tenant, tenant_app


def test_workspace_tool_visibility_is_isolated(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        disabled = client.patch(
            "/api/v1/tools/calculate",
            headers=tenant_a["headers"],
            json={"enabled": False},
        )
        tools_a = client.get("/api/v1/tools", headers=tenant_a["headers"]).json()
        tools_b = client.get("/api/v1/tools", headers=tenant_b["headers"]).json()

    calculate_a = next(item for item in tools_a["items"] if item["name"] == "calculate")
    calculate_b = next(item for item in tools_b["items"] if item["name"] == "calculate")
    assert disabled.status_code == 200
    assert calculate_a["enabled"] is False
    assert calculate_b["enabled"] is True


def test_workspace_scope_sets_agent_override(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        client.post(
            "/api/v1/agents",
            headers=tenant["headers"],
            json={"name": "chat", "tools": ["calculate"]},
        )
        updated = client.patch(
            "/api/v1/agents/chat/tools/calculate",
            headers=tenant["headers"],
            json={"enabled": False},
        )
        listed = client.get(
            "/api/v1/agents/chat/tools", headers=tenant["headers"]
        ).json()

    calculate = next(item for item in listed["items"] if item["name"] == "calculate")
    assert updated.status_code == 200
    assert calculate["enabled"] is False


class _RecordingClient(EchoLLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.tools_seen: list[str] = []

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        self.tools_seen = [tool.name for tool in (options.tools if options else [])]
        async for chunk in super().stream(messages, options=options):
            yield chunk


class _ForgedToolClient(EchoLLMClient):
    def __init__(self) -> None:
        self.calls = 0

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        self.calls += 1
        if self.calls == 1:
            yield StreamChunk(
                tool_calls=[
                    ToolCall(
                        id="forged",
                        name="calculate",
                        arguments='{"expression": "1+1"}',
                    )
                ],
                finish_reason="tool_calls",
            )
            return
        yield StreamChunk(delta="done", finish_reason="stop")


@pytest.mark.asyncio
async def test_disabled_tool_is_not_visible_to_model(tmp_path: Path) -> None:
    store = PlatformStore(PlatformSettings(db_path=str(tmp_path / "platform.db")))
    registry = create_default_tool_registry(ToolsSettings(allow_shell=False))
    policy = ToolPolicyService(store.tools, store.workspace_tools, store.agent_tools)
    policy.sync(registry)
    policy.set_workspace_tool(registry, "calculate", enabled=False, workspace_id=2)
    client = _RecordingClient()
    runtime = AgentRuntime(client, tools=registry, tool_policy=policy)

    with bind(workspace_id=2, user_id=1):
        await runtime.run(Agent(name="chat", tools=["calculate"]), "hello")

    assert "calculate" not in client.tools_seen


@pytest.mark.asyncio
async def test_forged_tool_call_cannot_bypass_workspace_policy(tmp_path: Path) -> None:
    store = PlatformStore(PlatformSettings(db_path=str(tmp_path / "platform.db")))
    registry = create_default_tool_registry(ToolsSettings(allow_shell=False))
    policy = ToolPolicyService(store.tools, store.workspace_tools, store.agent_tools)
    policy.sync(registry)
    policy.set_workspace_tool(registry, "calculate", enabled=False, workspace_id=2)
    client = _ForgedToolClient()
    runtime = AgentRuntime(client, tools=registry, tool_policy=policy)

    with bind(workspace_id=2, user_id=1):
        result = await runtime.run(Agent(name="chat", tools=["calculate"]), "hello")

    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert tool_messages
    assert "permission denied" in tool_messages[0].content

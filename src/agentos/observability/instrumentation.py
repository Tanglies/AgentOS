"""Helpers for mapping AgentOS requests to telemetry attributes."""

from __future__ import annotations

from typing import Any

from agentos.core.context import get_run_id, get_tool_name, get_user_id, get_workspace_id


def request_attributes(scope: dict[str, Any]) -> dict[str, Any]:
    """Build low-cardinality HTTP span attributes."""
    return {
        "http.method": scope.get("method"),
        "http.route": scope.get("path"),
        "workspace.id": get_workspace_id(),
        "user.id": get_user_id(),
    }


def runtime_attributes(agent: str, *, run_id: str | None = None) -> dict[str, Any]:
    """Build common runtime span attributes."""
    return {
        "agent.name": agent,
        "run.id": run_id or get_run_id(),
        "workspace.id": get_workspace_id(),
        "user.id": get_user_id(),
    }


def tool_attributes(tool_name: str, *, call_id: str | None = None) -> dict[str, Any]:
    """Build Tool span attributes without arguments or result content."""
    return {
        "tool.name": tool_name,
        "tool.call_id": call_id,
        "workspace.id": get_workspace_id(),
        "run.id": get_run_id(),
        "parent.tool_name": get_tool_name(),
    }


__all__ = ["request_attributes", "runtime_attributes", "tool_attributes"]

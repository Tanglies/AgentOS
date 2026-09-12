"""Workspace and Agent scoped Tool visibility policy."""

from __future__ import annotations

from agentos.core.context import get_workspace_id
from agentos.core.exceptions import NotFoundError
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.runtime.agent import Agent
from agentos.runtime.platform_repositories import (
    AgentToolRepository,
    ToolMetadataRepository,
    ToolRiskLevel,
    WorkspaceToolRepository,
)
from agentos.runtime.registry import AgentRegistry
from agentos.runtime.tools import Tool, ToolRegistry, current_tool_permissions_allowed


class ToolPolicyService:
    """Resolve the effective Tool allowlist for a Workspace and Agent."""

    def __init__(
        self,
        metadata: ToolMetadataRepository,
        workspace_tools: WorkspaceToolRepository,
        agent_tools: AgentToolRepository,
    ) -> None:
        self._metadata = metadata
        self._workspace_tools = workspace_tools
        self._agent_tools = agent_tools

    @staticmethod
    def _scope(workspace_id: int | None = None) -> int:
        return workspace_id or get_workspace_id() or DEFAULT_WORKSPACE_ID

    def sync(self, registry: ToolRegistry) -> None:
        """Mirror code-registered Tool metadata into the platform database."""
        for tool in registry.list():
            self._metadata.upsert(
                name=tool.name,
                category=tool.category,
                description=tool.description,
                risk_level=ToolRiskLevel(tool.risk_level),
            )

    def set_workspace_tool(
        self,
        registry: ToolRegistry,
        tool_name: str,
        *,
        enabled: bool,
        workspace_id: int | None = None,
    ):
        """Enable or disable a Tool for one Workspace."""
        if tool_name not in registry:
            raise NotFoundError(f"tool not found: {tool_name}", details={"tool": tool_name})
        return self._workspace_tools.set_enabled(
            self._scope(workspace_id), tool_name, enabled=enabled
        )

    def _agent_id(self, registry: AgentRegistry, agent_name: str, workspace_id: int) -> int | None:
        repository = getattr(registry, "repository", None)
        if repository is None or not hasattr(repository, "get_record"):
            return None
        record = repository.get_record(agent_name, workspace_id=workspace_id)
        return record.id if record is not None else None

    def set_agent_tool(
        self,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        agent_name: str,
        tool_name: str,
        *,
        enabled: bool,
        workspace_id: int | None = None,
    ):
        """Override Tool visibility for one Agent."""
        scope = self._scope(workspace_id)
        if tool_name not in tool_registry:
            raise NotFoundError(f"tool not found: {tool_name}", details={"tool": tool_name})
        agent_id = self._agent_id(agent_registry, agent_name, scope)
        if agent_id is None:
            raise NotFoundError(
                f"agent not found: {agent_name}", details={"agent": agent_name}
            )
        return self._agent_tools.set_enabled(
            scope, agent_id, tool_name, enabled=enabled
        )

    def list_workspace_tools(
        self,
        registry: ToolRegistry,
        *,
        workspace_id: int | None = None,
    ) -> list[tuple[Tool, bool]]:
        """Return all registered Tools with their Workspace-visible state."""
        scope = self._scope(workspace_id)
        metadata = {item.name: item for item in self._metadata.list()}
        overrides = self._workspace_tools.enabled_map(scope)
        result: list[tuple[Tool, bool]] = []
        for tool in registry.list():
            record = metadata.get(tool.name)
            enabled = record.enabled if record is not None else True
            if tool.risk_level == ToolRiskLevel.HIGH.value and tool.name not in overrides:
                enabled = False
            result.append((tool, overrides.get(tool.name, enabled)))
        return result

    def agent_tool_status(
        self,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        agent_name: str,
        *,
        workspace_id: int | None = None,
    ) -> list[tuple[Tool, bool]]:
        """Return Tool visibility for one Agent."""
        scope = self._scope(workspace_id)
        agent = agent_registry.get(agent_name, workspace_id=scope)
        agent_id = self._agent_id(agent_registry, agent_name, scope)
        overrides = (
            self._agent_tools.enabled_map(scope, agent_id)
            if agent_id is not None
            else {}
        )
        declared = set(agent.tools)
        workspace_status = {
            tool.name: enabled
            for tool, enabled in self.list_workspace_tools(
                tool_registry, workspace_id=scope
            )
        }
        return [
            (
                tool,
                workspace_status.get(tool.name, False)
                and (
                    overrides.get(tool.name, tool.name in declared)
                    if overrides
                    else tool.name in declared
                ),
            )
            for tool in tool_registry.list()
        ]

    def visible_tools(
        self,
        registry: ToolRegistry,
        agent: Agent,
        *,
        workspace_id: int | None = None,
        agent_id: int | None = None,
    ) -> list[Tool]:
        """Return Tools visible to the model for this Agent."""
        scope = self._scope(workspace_id)
        names = self.visible_tool_names(
            registry, agent, workspace_id=scope, agent_id=agent_id
        )
        return [registry.get(name) for name in names]

    def visible_tool_names(
        self,
        registry: ToolRegistry,
        agent: Agent,
        *,
        workspace_id: int | None = None,
        agent_id: int | None = None,
    ) -> list[str]:
        """Apply workspace, Agent, and API permission filters."""
        scope = self._scope(workspace_id)
        metadata = {item.name: item for item in self._metadata.list()}
        workspace_overrides = self._workspace_tools.enabled_map(scope)
        agent_overrides: dict[str, bool] = {}
        if agent_id is not None:
            agent_overrides = self._agent_tools.enabled_map(scope, agent_id)
        declared = set(agent.tools)
        visible: list[str] = []
        for tool in registry.list():
            global_record = metadata.get(tool.name)
            default_enabled = (
                global_record.enabled
                if global_record is not None
                else tool.risk_level != ToolRiskLevel.HIGH.value
            )
            if tool.risk_level == ToolRiskLevel.HIGH.value and tool.name not in workspace_overrides:
                default_enabled = False
            workspace_enabled = workspace_overrides.get(tool.name, default_enabled)
            agent_enabled = (
                agent_overrides.get(tool.name, tool.name in declared)
                if agent_overrides
                else tool.name in declared
            )
            if (
                workspace_enabled
                and agent_enabled
                and current_tool_permissions_allowed(tool.required_permissions)
            ):
                visible.append(tool.name)
        return sorted(visible)



__all__ = ["ToolPolicyService"]

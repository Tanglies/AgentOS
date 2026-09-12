"""Shared helpers for multi-tenant integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.runtime.api_keys import Permission
from agentos.runtime.platform_repositories import (
    UserRecord,
    WorkspaceMemberRecord,
    WorkspaceRecord,
    WorkspaceRole,
)

BOOTSTRAP_KEY = "sk-bootstrap-admin"
HEADER = "X-API-Key"


def tenant_settings(
    tmp_path: Path,
    *,
    quota: dict[str, Any] | None = None,
    tools: dict[str, Any] | None = None,
) -> Settings:
    """Build an isolated authenticated multi-tenant test application."""
    return Settings(
        _env_file=None,
        llm={"provider": "echo"},
        logging={"level": "ERROR"},
        auth={
            "enabled": True,
            "api_keys": [SecretStr(BOOTSTRAP_KEY)],
        },
        platform={"db_path": str(tmp_path / "platform.db")},
        registry={"persist": True, "db_path": str(tmp_path / "agents.db")},
        runs={"enabled": True, "db_path": str(tmp_path / "runs.db")},
        audit={"enabled": True, "db_path": str(tmp_path / "audit.db")},
        api_keys={"db_path": str(tmp_path / "api-keys.db")},
        memory={"long_term_db_path": str(tmp_path / "memory.db")},
        quota=quota or {},
        tools=tools or {},
    )


def tenant_app(
    tmp_path: Path,
    *,
    quota: dict[str, Any] | None = None,
    tools: dict[str, Any] | None = None,
) -> FastAPI:
    """Create an authenticated tenant test app."""
    return create_app(tenant_settings(tmp_path, quota=quota, tools=tools))


def headers(key: str = BOOTSTRAP_KEY) -> dict[str, str]:
    return {HEADER: key}


def tenant_permissions() -> list[str]:
    """Permissions suitable for ordinary tenant API keys."""
    return [
        item.value
        for item in Permission
        if item.value not in {Permission.ALL.value, Permission.API_KEY_ADMIN.value}
    ]


def create_tenant(
    client: TestClient,
    name: str,
    *,
    workspace_name: str | None = None,
) -> dict[str, Any]:
    """Create a user, Workspace, API key, and return their identifiers."""
    store = client.app.state.platform_store
    user = store.users.add(
        UserRecord(username=name, display_name=name.title())
    )
    if user.id is None:  # pragma: no cover
        raise RuntimeError("user id missing")
    workspace = store.workspaces.add(
        WorkspaceRecord(
            name=workspace_name or f"{name}-workspace",
            owner_id=user.id,
        )
    )
    if workspace.id is None:  # pragma: no cover
        raise RuntimeError("workspace id missing")
    store.members.add(
        WorkspaceMemberRecord(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.OWNER,
        )
    )
    issued = client.app.state.api_key_store.issue(
        f"{name}-key",
        user_id=user.id,
        workspace_id=workspace.id,
        permissions=tenant_permissions(),
    )
    return {
        "user_id": user.id,
        "workspace_id": workspace.id,
        "key": issued.key,
        "headers": headers(issued.key),
    }


def create_workspace_key(
    client: TestClient,
    *,
    user_id: int,
    workspace_id: int,
    name: str,
    permissions: list[str] | None = None,
) -> str:
    """Issue a key directly for a user/Workspace pair."""
    issued = client.app.state.api_key_store.issue(
        name,
        user_id=user_id,
        workspace_id=workspace_id,
        permissions=permissions or tenant_permissions(),
    )
    return issued.key


def default_workspace_key(
    client: TestClient,
    *,
    user_id: int,
    name: str,
) -> str:
    """Issue a key into the bootstrap default Workspace."""
    return create_workspace_key(
        client,
        user_id=user_id,
        workspace_id=DEFAULT_WORKSPACE_ID,
        name=name,
    )

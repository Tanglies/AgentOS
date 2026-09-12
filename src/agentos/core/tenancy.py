"""Tenant identity constants shared by platform components.

The default tenant is used by legacy single-tenant data and by the bootstrap
administrator key. Explicit workspace scoping always takes precedence.
"""

from __future__ import annotations

DEFAULT_USER_ID = 1
DEFAULT_WORKSPACE_ID = 1
DEFAULT_USERNAME = "bootstrap"
DEFAULT_DISPLAY_NAME = "Bootstrap Administrator"
DEFAULT_WORKSPACE_NAME = "Default Workspace"

__all__ = [
    "DEFAULT_DISPLAY_NAME",
    "DEFAULT_USERNAME",
    "DEFAULT_USER_ID",
    "DEFAULT_WORKSPACE_ID",
    "DEFAULT_WORKSPACE_NAME",
]

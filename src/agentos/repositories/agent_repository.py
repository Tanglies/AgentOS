"""Agent repository compatibility facade.

The implementation remains in :mod:`agentos.runtime.repositories` during the
platform migration so existing imports and behavior stay stable. New code can
import from the canonical ``agentos.repositories`` package.
"""

from agentos.runtime.repositories import AGENTS_SCHEMA, AgentRepository

__all__ = ["AGENTS_SCHEMA", "AgentRepository"]

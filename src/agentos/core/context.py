"""请求级上下文。

基于 :mod:`contextvars` 实现，可以在异步调用链中安全传递 request_id、run_id 等字段；
日志系统会自动读取这些字段并附加到每条日志上。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("agentos_request_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("agentos_run_id", default=None)
_agent_name: ContextVar[str | None] = ContextVar("agentos_agent_name", default=None)


def new_id(prefix: str = "") -> str:
    """生成带前缀的短标识。"""
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> Token[str | None]:
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def get_run_id() -> str | None:
    return _run_id.get()


def set_run_id(value: str | None) -> Token[str | None]:
    return _run_id.set(value)


def reset_run_id(token: Token[str | None]) -> None:
    _run_id.reset(token)


def get_agent_name() -> str | None:
    return _agent_name.get()


def set_agent_name(value: str | None) -> Token[str | None]:
    return _agent_name.set(value)


def reset_agent_name(token: Token[str | None]) -> None:
    _agent_name.reset(token)


def current_context() -> dict[str, str]:
    """返回当前上下文中的非空字段。"""
    fields = {
        "request_id": get_request_id(),
        "run_id": get_run_id(),
        "agent": get_agent_name(),
    }
    return {key: value for key, value in fields.items() if value}


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    """绑定 request_id 的上下文管理器，退出时自动恢复。"""
    resolved = request_id or new_id("req_")
    token = set_request_id(resolved)
    try:
        yield resolved
    finally:
        reset_request_id(token)
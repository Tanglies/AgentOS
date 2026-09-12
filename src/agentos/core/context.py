"""请求级上下文。

基于 :mod:`contextvars` 实现，可以在异步调用链中安全传递：

| 字段 | 含义 | 谁写入 |
| --- | --- | --- |
| ``trace_id`` | 一次完整调用链的标识 | 请求中间件生成或透传 |
| ``request_id`` | 单次 HTTP 请求 | 请求中间件 |
| ``run_id`` | 一次 Agent 运行 | AgentRuntime |
| ``agent_name`` | 当前 Agent | AgentRuntime |
| ``tool_name`` | 当前正在执行的工具 | ToolRegistry |
| ``actor`` | 调用方标识（密钥指纹） | 认证中间件 |

日志系统会自动读取这些字段并附加到每条日志上，因此一次调用
「HTTP → Runtime → LLM → Tool → Database」的完整链路可以靠
``trace_id`` 串起来。

除了逐字段的 set/get/reset，还提供 :func:`bind` 上下文管理器 ——
需要同时绑定多个字段时用它，退出会自动按相反顺序还原。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_REQUEST_ID: ContextVar[str | None] = ContextVar("agentos_request_id", default=None)
_TRACE_ID: ContextVar[str | None] = ContextVar("agentos_trace_id", default=None)
_RUN_ID: ContextVar[str | None] = ContextVar("agentos_run_id", default=None)
_AGENT_NAME: ContextVar[str | None] = ContextVar("agentos_agent_name", default=None)
_TOOL_NAME: ContextVar[str | None] = ContextVar("agentos_tool_name", default=None)
_ACTOR: ContextVar[str | None] = ContextVar("agentos_actor", default=None)

_FIELDS: dict[str, ContextVar[str | None]] = {
    "trace_id": _TRACE_ID,
    "request_id": _REQUEST_ID,
    "run_id": _RUN_ID,
    "agent_name": _AGENT_NAME,
    "tool_name": _TOOL_NAME,
    "actor": _ACTOR,
}


def new_id(prefix: str = "") -> str:
    """生成带前缀的短标识。"""
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def _get(field: str) -> str | None:
    return _FIELDS[field].get()


def _set(field: str, value: str | None) -> Token[str | None]:
    return _FIELDS[field].set(value)


def _reset(field: str, token: Token[str | None]) -> None:
    _FIELDS[field].reset(token)


def get_trace_id() -> str | None:
    return _get("trace_id")


def set_trace_id(value: str | None) -> Token[str | None]:
    return _set("trace_id", value)


def reset_trace_id(token: Token[str | None]) -> None:
    _reset("trace_id", token)


def get_request_id() -> str | None:
    return _get("request_id")


def set_request_id(value: str | None) -> Token[str | None]:
    return _set("request_id", value)


def reset_request_id(token: Token[str | None]) -> None:
    _reset("request_id", token)


def get_run_id() -> str | None:
    return _get("run_id")


def set_run_id(value: str | None) -> Token[str | None]:
    return _set("run_id", value)


def reset_run_id(token: Token[str | None]) -> None:
    _reset("run_id", token)


def get_agent_name() -> str | None:
    return _get("agent_name")


def set_agent_name(value: str | None) -> Token[str | None]:
    return _set("agent_name", value)


def reset_agent_name(token: Token[str | None]) -> None:
    _reset("agent_name", token)


def get_tool_name() -> str | None:
    return _get("tool_name")


def set_tool_name(value: str | None) -> Token[str | None]:
    return _set("tool_name", value)


def reset_tool_name(token: Token[str | None]) -> None:
    _reset("tool_name", token)


def get_actor() -> str | None:
    return _get("actor")


def set_actor(value: str | None) -> Token[str | None]:
    return _set("actor", value)


def reset_actor(token: Token[str | None]) -> None:
    _reset("actor", token)


def current_context() -> dict[str, str]:
    """返回当前上下文中的非空字段。"""
    return {key: value for key, value in ((k, v.get()) for k, v in _FIELDS.items()) if value}


@contextmanager
def bind(**fields: str | None) -> Iterator[dict[str, str]]:
    """临时绑定若干上下文字段，退出时按相反顺序还原。

    用法::

        with bind(run_id="run_x", agent_name="assistant"):
            ...  # 这段代码里打的所有日志都会带上这两个字段

    字段名必须是 :data:`_FIELDS` 里的键，写错会直接抛 ``ValueError``
    —— 静默忽略拼写错误会让排查变得很痛苦。
    """
    unknown = set(fields) - set(_FIELDS)
    if unknown:
        raise ValueError(f"unknown context field(s): {', '.join(sorted(unknown))}")

    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = []
    for key, value in fields.items():
        tokens.append((_FIELDS[key], _FIELDS[key].set(value)))
    try:
        yield current_context()
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    """绑定 request_id 的上下文管理器，退出时自动恢复。"""
    resolved = request_id or new_id("req_")
    with bind(request_id=resolved):
        yield resolved
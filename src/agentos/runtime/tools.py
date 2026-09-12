"""Tool Calling 基础设施。

工具（Tool）是 Agent 与外部世界交互的入口：模型只负责决定
「调用哪个工具、传什么参数」，真正执行由本模块完成，执行结果再作为
``tool`` 消息回填给模型，由模型组织成最终回答。

一次工具调用在 Runtime 中的完整链路：

1. 模型返回 ``tool_calls``
2. :class:`ToolRegistry` 按名称找到对应的 :class:`Tool`
3. :func:`validate_arguments` 按工具声明的 JSON Schema 校验参数
4. 执行 ``Tool.run()`` 得到文本结果
5. 结果包装为 :class:`ToolCallResult`，由 Runtime 回填成 ``tool`` 消息

设计取舍：

- 参数校验只覆盖常用 JSON Schema 子集（``required`` / ``type`` / ``enum``），
  不为此引入额外依赖；更复杂的校验可在 ``Tool.run()`` 内自行完成。
- 工具执行失败**不向上抛异常**，而是返回带错误文本的结果，
  让模型有机会自我修正（例如换个参数重试），也避免单次工具故障中断整个会话。
"""

from __future__ import annotations

import inspect
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from pydantic import BaseModel

from agentos.core.context import bind
from agentos.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from agentos.core.logging import get_logger
from agentos.llm.base import ToolCall, ToolSpec

logger = get_logger(__name__)

PermissionChecker = Callable[[str], bool]

_PERMISSION_CHECKER: ContextVar[PermissionChecker | None] = ContextVar(
    "agentos_tool_permission_checker", default=None
)


@contextmanager
def tool_permission_scope(checker: PermissionChecker | None) -> Iterator[None]:
    """在认证请求中绑定工具权限检查器。

    检查器为 ``None`` 时表示当前不在 HTTP 认证上下文中（例如嵌入式
    Runtime、单元测试或显式关闭认证），此时保持既有行为，不额外拦截。
    """
    token: Token[PermissionChecker | None] = _PERMISSION_CHECKER.set(checker)
    try:
        yield
    finally:
        _PERMISSION_CHECKER.reset(token)


def _check_tool_permissions(required: Iterable[str]) -> None:
    checker = _PERMISSION_CHECKER.get()
    if checker is None:
        return
    denied = [permission for permission in required if not checker(permission)]
    if denied:
        raise PermissionDeniedError(
            "tool execution permission denied",
            details={"required": denied},
        )


_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "array": (list,),
    "object": (dict,),
}


def truncate_text(text: str, limit: int) -> str:
    """按字符数截断文本，并附上长度说明。"""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [输出已截断，完整长度 {len(text)} 字符]"


class ToolArgumentError(ValidationError):
    """工具参数不符合声明的 JSON Schema。"""

    code = "tool_argument_error"
    message = "Tool arguments failed validation"


def _matches_type(value: Any, expected: str) -> bool:
    """按 JSON Schema 的 ``type`` 关键字判断值是否合法。

    注意 ``bool`` 在 Python 中是 ``int`` 的子类，需要单独排除，
    否则 ``True`` 会被误判为合法的整数。
    """
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    types = _JSON_TYPES.get(expected)
    return True if types is None else isinstance(value, types)


def validate_arguments(
    schema: dict[str, Any], arguments: dict[str, Any], *, tool_name: str = ""
) -> dict[str, Any]:
    """按工具声明的 JSON Schema 校验参数，返回参数副本。

    支持的子集：``type`` / ``properties`` / ``required`` / ``enum``。
    未在 ``properties`` 中声明的字段会被保留，交由 ``Tool.run()`` 自行处理。
    """
    where = f"tool '{tool_name}'" if tool_name else "tool"
    if not isinstance(arguments, dict):
        raise ToolArgumentError(
            f"{where} arguments must be a JSON object",
            details={"tool": tool_name, "received": type(arguments).__name__},
        )

    if schema.get("type", "object") != "object":
        # 仅支持对象型参数；非对象 schema 不做进一步校验。
        return dict(arguments)

    properties = schema.get("properties") or {}
    required = schema.get("required") or []

    missing = [name for name in required if name not in arguments]
    if missing:
        raise ToolArgumentError(
            f"{where} missing required argument(s): {', '.join(missing)}",
            details={"tool": tool_name, "missing": missing, "required": list(required)},
        )

    for key, value in arguments.items():
        rule = properties.get(key)
        if not isinstance(rule, dict):
            continue
        expected = rule.get("type")
        if expected and not _matches_type(value, expected):
            raise ToolArgumentError(
                f"{where} argument '{key}' must be {expected}",
                details={
                    "tool": tool_name,
                    "argument": key,
                    "expected": expected,
                    "received": type(value).__name__,
                },
            )
        allowed = rule.get("enum")
        if allowed is not None and value not in allowed:
            raise ToolArgumentError(
                f"{where} argument '{key}' must be one of {allowed}",
                details={"tool": tool_name, "argument": key, "allowed": allowed},
            )

    return dict(arguments)


class Tool(ABC):
    """工具抽象基类。

    子类声明 ``name`` / ``description`` / ``parameters``（JSON Schema）
    并实现 :meth:`run` 即可。
    """

    name: str = ""
    description: str = ""
    required_permissions: tuple[str, ...] = ("tool:execute",)
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    @abstractmethod
    async def run(self, **kwargs: Any) -> str:
        """执行工具，返回供模型阅读的文本结果。"""

    def spec(self) -> ToolSpec:
        """转换为暴露给模型的工具声明。"""
        return ToolSpec(
            name=self.name, description=self.description, parameters=self.parameters
        )

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """按自身声明的 Schema 校验参数。"""
        return validate_arguments(self.parameters, arguments, tool_name=self.name)


class FunctionTool(Tool):
    """用一个现成函数快速构造工具。

    ``func`` 可以是同步函数或协程函数；返回值不是字符串时会被 JSON 序列化。
    """

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self._func = func

    async def run(self, **kwargs: Any) -> str:
        result = self._func(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)


class ToolCallResult(BaseModel):
    """一次工具调用的执行结果。"""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


class ToolRegistry:
    """进程内工具注册表。"""

    def __init__(self, tools: Iterable[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or ():
            self.register(tool)

    def register(self, tool: Tool, *, overwrite: bool = False) -> Tool:
        """注册工具；重名时默认抛 :class:`ConflictError`。"""
        if not tool.name:
            raise ValidationError("tool name must not be empty")
        if tool.name in self._tools and not overwrite:
            raise ConflictError(
                f"tool already registered: {tool.name}", details={"tool": tool.name}
            )
        self._tools[tool.name] = tool
        return tool

    def unregister(self, name: str) -> None:
        """注销工具，不存在时报错。"""
        if name not in self._tools:
            raise NotFoundError(f"tool not found: {name}", details={"tool": name})
        del self._tools[name]

    def get(self, name: str) -> Tool:
        """按名称获取工具。"""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise NotFoundError(
                f"tool not found: {name}",
                details={"tool": name, "available": sorted(self._tools)},
            ) from exc

    def list(self) -> list[Tool]:
        """返回全部工具（按名称排序）。"""
        return [self._tools[name] for name in sorted(self._tools)]

    def specs(self, names: Iterable[str] | None = None) -> list[ToolSpec]:
        """返回工具声明；传入 ``names`` 时按给定顺序筛选。"""
        if names is None:
            return [tool.spec() for tool in self.list()]
        return [self.get(name).spec() for name in names]

    async def execute(self, tool_call: ToolCall) -> ToolCallResult:
        """执行一次工具调用。

        工具不存在、参数非法或执行抛错时，都转换成 ``is_error=True``
        的结果文本回填给模型，而不是让整次 Agent 运行失败。

        整个过程绑定 ``tool_name``，让执行期间的日志（含失败）都能看出
        是哪个工具 —— 否则一次运行调了多个工具时日志会混在一起。
        """
        with bind(tool_name=tool_call.name):
            return await self._execute(tool_call)

    async def _execute(self, tool_call: ToolCall) -> ToolCallResult:
        try:
            tool = self.get(tool_call.name)
        except NotFoundError as exc:
            logger.warning(
                "tool not found",
                extra={"extra_fields": {"tool": tool_call.name, "call_id": tool_call.id}},
            )
            return self._error(tool_call, f"Error: {exc.message}")

        _check_tool_permissions(tool.required_permissions)

        try:
            raw_arguments = json.loads(tool_call.arguments or "{}")
        except ValueError as exc:
            logger.warning(
                "tool arguments are not valid json",
                extra={"extra_fields": {"tool": tool_call.name, "call_id": tool_call.id}},
            )
            return self._error(tool_call, f"Error: arguments must be valid JSON: {exc}")

        if not isinstance(raw_arguments, dict):
            return self._error(tool_call, "Error: arguments must be a JSON object")

        try:
            arguments = tool.validate_arguments(raw_arguments)
        except ValidationError as exc:
            logger.warning(
                "tool arguments failed validation",
                extra={
                    "extra_fields": {
                        "tool": tool_call.name,
                        "call_id": tool_call.id,
                        "details": exc.details,
                    }
                },
            )
            return self._error(tool_call, f"Error: {exc.message}")

        try:
            content = await tool.run(**arguments)
        except Exception as exc:  # noqa: BLE001 - 工具异常需转为可回填的文本
            logger.exception(
                "tool execution failed",
                extra={"extra_fields": {"tool": tool_call.name, "call_id": tool_call.id}},
            )
            return self._error(
                tool_call, f"Error: tool execution failed: {type(exc).__name__}: {exc}"
            )

        logger.info(
            "tool executed",
            extra={
                "extra_fields": {
                    "tool": tool_call.name,
                    "call_id": tool_call.id,
                    "result_length": len(content),
                }
            },
        )
        return ToolCallResult(
            tool_call_id=tool_call.id, name=tool_call.name, content=content
        )

    @staticmethod
    def _error(tool_call: ToolCall, content: str) -> ToolCallResult:
        return ToolCallResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            content=content,
            is_error=True,
        )

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

"""内置示例工具。

这些工具不依赖任何外部服务与密钥，用于验证 Tool Calling 全链路，
同时作为自定义工具的参考实现。

刻意只使用标准库：``zoneinfo`` 在 Windows 上需要额外的 ``tzdata`` 包，
因此时间工具改用 ``datetime.timezone`` 的固定 UTC 偏移实现。
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from agentos.core.config import ToolsSettings
from agentos.runtime.local_tools import create_local_tools
from agentos.runtime.long_term_memory import LongTermMemory
from agentos.runtime.memory_tools import create_memory_tools
from agentos.runtime.plan_tools import create_plan_tools
from agentos.runtime.tools import Tool, ToolRegistry
from agentos.runtime.web_tools import create_web_tools

MAX_POWER_EXPONENT = 64

_ALLOWED_BINARY_OPS: dict[type[ast.AST], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARY_OPS: dict[type[ast.AST], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _evaluate(node: ast.AST) -> Any:
    """递归求值算术表达式。

    只放行白名单内的节点类型，不执行属性访问、函数调用或变量名查找，
    因此不存在 ``eval`` 那样的代码注入风险。
    """
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)

    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, int | float) and not isinstance(value, bool):
            return value
        raise ValueError(f"不支持的常量：{value!r}")

    if isinstance(node, ast.BinOp):
        binary_op = _ALLOWED_BINARY_OPS.get(type(node.op))
        if binary_op is None:
            raise ValueError(f"不支持的运算符：{type(node.op).__name__}")
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_POWER_EXPONENT:
            raise ValueError(f"指数过大，上限为 {MAX_POWER_EXPONENT}")
        return binary_op(left, right)

    if isinstance(node, ast.UnaryOp):
        unary_op = _ALLOWED_UNARY_OPS.get(type(node.op))
        if unary_op is None:
            raise ValueError(f"不支持的一元运算符：{type(node.op).__name__}")
        return unary_op(_evaluate(node.operand))

    raise ValueError(f"不支持的表达式元素：{type(node).__name__}")


class CalculateTool(Tool):
    """执行基础算术运算。"""

    name = "calculate"
    description = "计算一个基础算术表达式，支持 + - * / // % ** 与括号。"
    category = "general"
    risk_level = "low"
    parallel_safe = True
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "要计算的算术表达式，例如 (12 + 8) * 3",
            }
        },
        "required": ["expression"],
    }

    async def run(self, expression: str) -> str:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            return f"表达式语法错误：{exc.msg}"
        try:
            value = _evaluate(tree)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            return f"无法计算：{exc}"
        return f"{expression} = {value}"


class GetCurrentTimeTool(Tool):
    """查询当前日期与时间。"""

    name = "get_current_time"
    description = (
        "获取当前日期和时间。可用 utc_offset_hours 指定与 UTC 的小时偏移"
        "（例如北京时间/上海为 8），不传则返回 UTC 时间。"
    )
    category = "general"
    risk_level = "low"
    parallel_safe = True
    parameters = {
        "type": "object",
        "properties": {
            "utc_offset_hours": {
                "type": "integer",
                "description": "与 UTC 的小时偏移，范围 -12 到 14，例如上海为 8",
            }
        },
    }

    async def run(self, utc_offset_hours: int = 0) -> str:
        if not -12 <= utc_offset_hours <= 14:
            return f"偏移量超出范围（-12 到 14）：{utc_offset_hours}"
        tz = timezone(timedelta(hours=utc_offset_hours))
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S UTC%z")


def create_default_tool_registry(
    settings: ToolsSettings | None = None,
    *,
    long_term: LongTermMemory | None = None,
) -> ToolRegistry:
    """创建默认工具注册表。

    包含通用工具、按配置启用的本地与联网工具，
    以及在启用长期记忆时附加的 ``remember`` / ``recall``。
    """
    resolved = settings or ToolsSettings()
    tools: list[Tool] = [GetCurrentTimeTool(), CalculateTool()]
    tools.extend(create_local_tools(resolved))
    tools.extend(create_web_tools(resolved))
    if long_term is not None:
        tools.extend(create_memory_tools(long_term))
    tools.extend(create_plan_tools())
    return ToolRegistry(tools, default_timeout_seconds=resolved.default_timeout_seconds)

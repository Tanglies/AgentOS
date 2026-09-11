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

from agentos.runtime.tools import Tool, ToolRegistry

MAX_POWER_EXPONENT = 64

# 默认助手 Agent 启用的内置工具；名称需与下方工具类的 name 保持一致。
DEFAULT_AGENT_TOOLS: tuple[str, ...] = ("get_current_time", "calculate")

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


def create_default_tool_registry() -> ToolRegistry:
    """创建包含全部内置工具的工具注册表。"""
    return ToolRegistry([GetCurrentTimeTool(), CalculateTool()])
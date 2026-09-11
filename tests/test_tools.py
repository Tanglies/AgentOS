"""Tool Calling 基础设施测试。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agentos.core.exceptions import ConflictError, NotFoundError, ValidationError
from agentos.llm.base import ToolCall
from agentos.runtime import (
    CalculateTool,
    FunctionTool,
    GetCurrentTimeTool,
    Tool,
    ToolArgumentError,
    ToolRegistry,
    create_default_tool_registry,
    validate_arguments,
)


class EchoTool(Tool):
    """记录调用参数的测试工具。"""

    name = "echo"
    description = "回显参数"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "times": {"type": "integer"},
        },
        "required": ["text"],
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return f"ok:{kwargs}"


class BoomTool(Tool):
    """执行时抛异常的工具，用于验证错误回填。"""

    name = "boom"
    parameters = {"type": "object", "properties": {}}

    async def run(self, **kwargs: Any) -> str:
        raise RuntimeError("kaboom")


# --- 工具声明与参数校验 ---------------------------------------------------


def test_tool_spec_serializes_to_provider_payload() -> None:
    payload = EchoTool().spec().to_provider_payload()

    assert payload["type"] == "function"
    assert payload["function"]["name"] == "echo"
    assert payload["function"]["description"] == "回显参数"
    assert payload["function"]["parameters"]["required"] == ["text"]


def test_validate_arguments_accepts_valid_input() -> None:
    result = validate_arguments(EchoTool.parameters, {"text": "hi", "times": 2})

    assert result == {"text": "hi", "times": 2}


def test_validate_arguments_rejects_missing_required() -> None:
    with pytest.raises(ToolArgumentError) as excinfo:
        validate_arguments(EchoTool.parameters, {}, tool_name="echo")

    assert excinfo.value.details["missing"] == ["text"]
    assert excinfo.value.code == "tool_argument_error"


def test_validate_arguments_rejects_wrong_type() -> None:
    with pytest.raises(ToolArgumentError) as excinfo:
        validate_arguments(EchoTool.parameters, {"text": 1}, tool_name="echo")

    assert excinfo.value.details["expected"] == "string"


def test_validate_arguments_rejects_bool_for_integer() -> None:
    """bool 是 int 的子类，必须单独排除，否则 True 会被当成合法整数。"""
    with pytest.raises(ToolArgumentError):
        validate_arguments(EchoTool.parameters, {"text": "x", "times": True})


def test_validate_arguments_rejects_number_for_string() -> None:
    with pytest.raises(ToolArgumentError):
        validate_arguments(EchoTool.parameters, {"text": 3.14})


def test_validate_arguments_rejects_value_outside_enum() -> None:
    schema = {
        "type": "object",
        "properties": {"unit": {"type": "string", "enum": ["c", "f"]}},
    }

    with pytest.raises(ToolArgumentError) as excinfo:
        validate_arguments(schema, {"unit": "k"}, tool_name="t")

    assert excinfo.value.details["allowed"] == ["c", "f"]


def test_validate_arguments_keeps_undeclared_fields() -> None:
    """未在 properties 中声明的字段保留，交由 Tool.run 自行处理。"""
    result = validate_arguments(EchoTool.parameters, {"text": "hi", "extra": 1})

    assert result["extra"] == 1


def test_validate_arguments_rejects_non_object() -> None:
    with pytest.raises(ToolArgumentError):
        validate_arguments(EchoTool.parameters, ["not", "a", "dict"])  # type: ignore[arg-type]


# --- 工具注册表 -----------------------------------------------------------


def test_registry_register_duplicate_conflicts() -> None:
    registry = ToolRegistry([EchoTool()])

    with pytest.raises(ConflictError):
        registry.register(EchoTool())

    assert len(registry) == 1
    assert "echo" in registry


def test_registry_register_empty_name_is_rejected() -> None:
    class NamelessTool(Tool):
        async def run(self, **kwargs: Any) -> str:
            return "x"

    with pytest.raises(ValidationError):
        ToolRegistry([NamelessTool()])


def test_registry_unregister_and_get() -> None:
    registry = ToolRegistry([EchoTool()])

    registry.unregister("echo")

    assert len(registry) == 0
    with pytest.raises(NotFoundError):
        registry.get("echo")


def test_registry_get_unknown_lists_available() -> None:
    registry = create_default_tool_registry()

    with pytest.raises(NotFoundError) as excinfo:
        registry.get("ghost")

    assert "calculate" in excinfo.value.details["available"]


def test_registry_specs_filters_by_name() -> None:
    registry = create_default_tool_registry()

    assert [spec.name for spec in registry.specs(["calculate"])] == ["calculate"]


# --- 工具执行与错误回填 ---------------------------------------------------


async def test_registry_executes_tool_and_parses_arguments() -> None:
    tool = EchoTool()
    registry = ToolRegistry([tool])

    result = await registry.execute(
        ToolCall(id="c1", name="echo", arguments=json.dumps({"text": "hi"}))
    )

    assert result.is_error is False
    assert result.tool_call_id == "c1"
    assert result.name == "echo"
    assert tool.calls == [{"text": "hi"}]


async def test_registry_reports_unknown_tool_as_error_result() -> None:
    result = await ToolRegistry().execute(ToolCall(id="c1", name="ghost", arguments="{}"))

    assert result.is_error is True
    assert "not found" in result.content


async def test_registry_reports_invalid_json_as_error_result() -> None:
    registry = ToolRegistry([EchoTool()])

    result = await registry.execute(ToolCall(id="c1", name="echo", arguments="not-json"))

    assert result.is_error is True
    assert "valid JSON" in result.content


async def test_registry_reports_non_object_arguments_as_error_result() -> None:
    registry = ToolRegistry([EchoTool()])

    result = await registry.execute(ToolCall(id="c1", name="echo", arguments="[1, 2]"))

    assert result.is_error is True
    assert "JSON object" in result.content


async def test_registry_reports_validation_failure_as_error_result() -> None:
    registry = ToolRegistry([EchoTool()])

    result = await registry.execute(ToolCall(id="c1", name="echo", arguments="{}"))

    assert result.is_error is True
    assert "required" in result.content


async def test_registry_reports_tool_exception_as_error_result() -> None:
    registry = ToolRegistry([BoomTool()])

    result = await registry.execute(ToolCall(id="c1", name="boom", arguments="{}"))

    assert result.is_error is True
    assert "kaboom" in result.content
    assert "RuntimeError" in result.content


# --- FunctionTool --------------------------------------------------------


def test_function_tool_exposes_name_and_description() -> None:
    tool = FunctionTool("add", lambda a, b: a + b, description="求和")

    assert tool.name == "add"
    assert tool.description == "求和"
    assert tool.spec().name == "add"


async def test_function_tool_serializes_non_string_result_to_json() -> None:
    tool = FunctionTool("stats", lambda: {"ok": True})

    assert json.loads(await tool.run()) == {"ok": True}


async def test_function_tool_awaits_coroutine_functions() -> None:
    async def slow(value: str) -> str:
        return f"got:{value}"

    tool = FunctionTool("slow", slow)

    assert await tool.run(value="x") == "got:x"


# --- 内置工具 -------------------------------------------------------------


async def test_calculate_tool_evaluates_expression() -> None:
    assert await CalculateTool().run(expression="(12 + 8) * 3") == "(12 + 8) * 3 = 60"


async def test_calculate_tool_rejects_function_call_injection() -> None:
    output = await CalculateTool().run(expression="__import__('os').system('echo hi')")

    assert "无法计算" in output
    assert "不支持的表达式元素" in output


async def test_calculate_tool_rejects_attribute_access_injection() -> None:
    output = await CalculateTool().run(expression="(1).__class__")

    assert "无法计算" in output


async def test_calculate_tool_handles_zero_division() -> None:
    assert "无法计算" in await CalculateTool().run(expression="1/0")


async def test_calculate_tool_handles_syntax_error() -> None:
    assert "语法错误" in await CalculateTool().run(expression="1 +")


async def test_calculate_tool_rejects_huge_exponent() -> None:
    assert "指数过大" in await CalculateTool().run(expression="2**1000")


async def test_calculate_tool_supports_negative_and_modulo() -> None:
    assert await CalculateTool().run(expression="-7 % 3") == "-7 % 3 = 2"


async def test_get_current_time_tool_reports_utc_offset() -> None:
    output = await GetCurrentTimeTool().run(utc_offset_hours=8)

    assert "UTC+0800" in output


async def test_get_current_time_tool_defaults_to_utc() -> None:
    output = await GetCurrentTimeTool().run()

    assert "UTC+0000" in output


async def test_get_current_time_tool_rejects_out_of_range_offset() -> None:
    assert "超出范围" in await GetCurrentTimeTool().run(utc_offset_hours=99)


def test_default_tool_registry_contains_builtin_tools() -> None:
    registry = create_default_tool_registry()

    names = {tool.name for tool in registry.list()}
    # 通用工具始终存在；本地工具随配置增减，因此用子集断言
    assert {"calculate", "get_current_time"} <= names
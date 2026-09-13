"""Rule-based Evaluation evaluator tests."""

from __future__ import annotations

import pytest

from agentos.evaluation import EvaluationCase
from agentos.evaluation.evaluators import (
    ContainsEvaluator,
    ExactMatchEvaluator,
    ForbiddenToolEvaluator,
    RuleEvaluator,
    ToolCallEvaluator,
)
from agentos.llm.base import TokenUsage, ToolCall
from agentos.runtime.message import Message
from agentos.runtime.runtime import RunResult


def _run(
    output: str = "60",
    *,
    tools: list[str] | None = None,
    duration_ms: float = 12.0,
    tokens: int = 20,
) -> RunResult:
    tool_calls = [
        ToolCall(id=f"t{i}", name=name)
        for i, name in enumerate(tools or [])
    ]
    messages = [Message.assistant("", tool_calls=tool_calls)]
    messages.append(Message.assistant(output))
    return RunResult(
        run_id="run_eval",
        agent="assistant",
        output=output,
        messages=messages,
        duration_ms=duration_ms,
        usage=TokenUsage(total_tokens=tokens),
    )


@pytest.mark.asyncio
async def test_exact_match() -> None:
    case = EvaluationCase(id="a", input="x", expected_output="Hello World")

    result = await ExactMatchEvaluator().evaluate(case, _run(" hello   world "))

    assert result.passed is True
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_contains() -> None:
    case = EvaluationCase(id="a", input="x", expected_output="60")

    result = await ContainsEvaluator().evaluate(case, _run("结果是 60 元"))

    assert result.passed is True


@pytest.mark.asyncio
async def test_tool_call_uses_real_trajectory() -> None:
    case = EvaluationCase(id="a", input="x", expected_tools=["calculate"])

    passed = await ToolCallEvaluator().evaluate(
        case, _run("???? calculate", tools=["calculate"])
    )
    failed = await ToolCallEvaluator().evaluate(case, _run("我调用了 calculate"))

    assert passed.passed is True
    assert failed.passed is False


@pytest.mark.asyncio
async def test_forbidden_tool() -> None:
    case = EvaluationCase(id="a", input="x", forbidden_tools=["run_command"])

    result = await ForbiddenToolEvaluator().evaluate(case, _run(tools=["run_command"]))

    assert result.passed is False


@pytest.mark.asyncio
async def test_rule_evaluator() -> None:
    case = EvaluationCase(
        id="a",
        input="x",
        metadata={
            "rules": [
                {"type": "contains", "value": "60"},
                {"type": "max_latency_ms", "value": 20},
                {"type": "tool_called", "value": "calculate"},
            ]
        },
    )

    result = await RuleEvaluator().evaluate(case, _run("60", tools=["calculate"]))

    assert result.passed is True
    assert result.score == 1.0

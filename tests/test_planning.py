"""Planning 测试：计划模型、计划工具、运行时注入与 API。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from fastapi.testclient import TestClient

from agentos.llm.base import (
    CompletionOptions,
    LLMClient,
    LLMMessage,
    LLMResponse,
    StreamChunk,
    ToolCall,
)
from agentos.runtime import Agent, AgentRuntime, ToolRegistry
from agentos.runtime.plan_tools import MAX_STEPS, create_plan_tools
from agentos.runtime.planning import (
    ExecutionPlan,
    PlanStep,
    StepStatus,
    build_plan,
    get_plan,
    reset_plan,
    set_plan,
)


class PlanScriptClient(LLMClient):
    """按脚本走「创建计划 → 更新步骤 → 收尾」三轮。"""

    provider = "plan-script"

    def __init__(self) -> None:
        self.round = 0
        self.seen_system: list[str] = []

    async def complete(
        self, messages: Sequence[LLMMessage], *, options: CompletionOptions | None = None
    ) -> LLMResponse:  # pragma: no cover - 仅满足抽象方法
        raise NotImplementedError

    async def stream(
        self, messages: Sequence[LLMMessage], *, options: CompletionOptions | None = None
    ) -> AsyncIterator[StreamChunk]:
        self.round += 1
        system = next((m.content for m in messages if m.role == "system"), "")
        self.seen_system.append(system)

        if self.round == 1:
            yield StreamChunk(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="create_plan",
                        arguments=(
                            '{"goal": "写调研报告", "steps": ["收集资料", "整理要点", "撰写成文"]}'
                        ),
                    )
                ],
                finish_reason="tool_calls",
            )
            return

        if self.round == 2:
            yield StreamChunk(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="update_plan_step",
                        arguments='{"step_id": 1, "status": "completed"}',
                    )
                ],
                finish_reason="tool_calls",
            )
            return

        yield StreamChunk(delta="调研报告已完成。")
        yield StreamChunk(finish_reason="stop")


# --- 计划模型 -------------------------------------------------------------


def test_build_plan_numbers_steps_from_one() -> None:
    plan = build_plan("写报告", ["收集资料", "整理要点"])

    assert [step.id for step in plan.steps] == [1, 2]
    assert plan.goal == "写报告"


def test_build_plan_skips_blank_steps() -> None:
    plan = build_plan("目标", ["有效", "   ", ""])

    assert [step.description for step in plan.steps] == ["有效"]


def test_render_uses_status_markers() -> None:
    plan = build_plan("目标", ["第一步", "第二步", "第三步"])
    plan.find(1).status = StepStatus.COMPLETED
    plan.find(2).status = StepStatus.IN_PROGRESS

    text = plan.render()

    assert "[x] 1. 第一步" in text
    assert "[~] 2. 第二步" in text
    assert "[ ] 3. 第三步" in text
    assert "进度：1/3 已完成" in text


def test_is_done_requires_all_steps_completed() -> None:
    plan = build_plan("目标", ["一", "二"])

    assert plan.is_done is False
    for step in plan.steps:
        step.status = StepStatus.COMPLETED
    assert plan.is_done is True


def test_empty_plan_is_not_done() -> None:
    assert ExecutionPlan().is_done is False


def test_find_returns_none_for_unknown_step() -> None:
    plan = build_plan("目标", ["一"])

    assert plan.find(1) is not None
    assert plan.find(99) is None


def test_plan_steps_default_to_pending() -> None:
    assert PlanStep(id=1, description="x").status == StepStatus.PENDING


# --- 运行期上下文 ---------------------------------------------------------


def test_plan_context_is_isolated_and_restorable() -> None:
    assert get_plan() is None

    token = set_plan(build_plan("目标", ["一"]))
    assert get_plan() is not None

    reset_plan(token)
    assert get_plan() is None


# --- 计划工具 -------------------------------------------------------------


def test_create_plan_tools_exposes_two_tools() -> None:
    names = [tool.name for tool in create_plan_tools()]

    assert names == ["create_plan", "update_plan_step"]


async def test_create_plan_tool_sets_current_plan() -> None:
    registry = ToolRegistry(create_plan_tools())

    result = await registry.execute(
        ToolCall(
            id="c1",
            name="create_plan",
            arguments='{"goal": "调研", "steps": ["查资料", "写结论"]}',
        )
    )

    assert result.is_error is False
    assert "计划已创建" in result.content
    plan = get_plan()
    assert plan is not None
    assert [step.description for step in plan.steps] == ["查资料", "写结论"]


async def test_create_plan_tool_rejects_empty_steps() -> None:
    registry = ToolRegistry(create_plan_tools())

    result = await registry.execute(
        ToolCall(id="c1", name="create_plan", arguments='{"goal": "x", "steps": []}')
    )

    assert "steps 不能为空" in result.content


async def test_create_plan_tool_truncates_too_many_steps() -> None:
    registry = ToolRegistry(create_plan_tools())
    steps = ", ".join(f'"步骤{i}"' for i in range(MAX_STEPS + 5))

    await registry.execute(
        ToolCall(
            id="c1", name="create_plan", arguments=f'{{"goal": "x", "steps": [{steps}]}}'
        )
    )

    plan = get_plan()
    assert plan is not None
    assert len(plan.steps) == MAX_STEPS


async def test_update_plan_step_tool_changes_status() -> None:
    registry = ToolRegistry(create_plan_tools())
    await registry.execute(
        ToolCall(
            id="c1",
            name="create_plan",
            arguments='{"goal": "x", "steps": ["一", "二"]}',
        )
    )

    result = await registry.execute(
        ToolCall(
            id="c2",
            name="update_plan_step",
            arguments='{"step_id": 2, "status": "completed"}',
        )
    )

    assert "已更新步骤 2" in result.content
    plan = get_plan()
    assert plan is not None
    assert plan.find(2).status == StepStatus.COMPLETED


async def test_update_plan_step_tool_reports_missing_plan() -> None:
    registry = ToolRegistry(create_plan_tools())

    result = await registry.execute(
        ToolCall(
            id="c1",
            name="update_plan_step",
            arguments='{"step_id": 1, "status": "completed"}',
        )
    )

    assert "还没有执行计划" in result.content


async def test_update_plan_step_tool_reports_unknown_step() -> None:
    registry = ToolRegistry(create_plan_tools())
    await registry.execute(
        ToolCall(id="c1", name="create_plan", arguments='{"goal": "x", "steps": ["一"]}')
    )

    result = await registry.execute(
        ToolCall(
            id="c2",
            name="update_plan_step",
            arguments='{"step_id": 9, "status": "completed"}',
        )
    )

    assert "不存在" in result.content


async def test_update_plan_step_tool_rejects_invalid_status() -> None:
    registry = ToolRegistry(create_plan_tools())
    await registry.execute(
        ToolCall(id="c1", name="create_plan", arguments='{"goal": "x", "steps": ["一"]}')
    )

    result = await registry.execute(
        ToolCall(
            id="c2", name="update_plan_step", arguments='{"step_id": 1, "status": "done"}'
        )
    )

    assert result.is_error is True


# --- Runtime 集成 ---------------------------------------------------------


async def test_runtime_injects_plan_into_system_prompt() -> None:
    client = PlanScriptClient()
    runtime = AgentRuntime(client)

    await runtime.run(Agent(name="planner", system_prompt="你是规划助手"), "做调研")

    # 第 1 轮还没有计划；第 2 轮起应该能看到
    assert "[执行计划]" not in client.seen_system[0]
    assert "[执行计划]" in client.seen_system[1]
    assert "你是规划助手" in client.seen_system[1]


async def test_runtime_returns_final_plan() -> None:
    runtime = AgentRuntime(PlanScriptClient())

    result = await runtime.run(Agent(name="planner", system_prompt="x"), "做调研")

    assert result.plan is not None
    assert result.plan.goal == "写调研报告"
    assert result.plan.find(1).status == StepStatus.COMPLETED
    assert result.plan.completed == 1


async def test_runtime_resets_plan_between_runs() -> None:
    client = PlanScriptClient()
    runtime = AgentRuntime(client)
    agent = Agent(name="planner", system_prompt="x")

    await runtime.run(agent, "第一次")
    assert get_plan() is None  # 运行结束后上下文已还原

    client.round = 0  # 让脚本客户端重新从「创建计划」开始
    second = await runtime.run(agent, "第二次")

    assert second.plan is not None
    assert second.plan.completed == 1  # 不是上一轮累积的


async def test_runtime_without_plan_has_no_plan_in_result() -> None:
    from agentos.llm import EchoLLMClient

    runtime = AgentRuntime(EchoLLMClient())

    result = await runtime.run(Agent(name="chat", system_prompt="x"), "你好")

    assert result.plan is None
    assert "[执行计划]" not in result.messages[0].content


# --- API ------------------------------------------------------------------


def test_plan_tools_are_registered(client: TestClient) -> None:
    names = {item["name"] for item in client.get("/api/v1/tools").json()["items"]}

    assert {"create_plan", "update_plan_step"} <= names


def test_run_response_has_plan_field(client: TestClient) -> None:
    body = client.post("/api/v1/runs", json={"input": "你好"}).json()

    assert "plan" in body
    assert body["plan"] is None


def test_openapi_exposes_plan_in_run_response(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    properties = schema["components"]["schemas"]["RunResponse"]["properties"]

    assert "plan" in properties
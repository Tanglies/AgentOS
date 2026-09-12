"""计划工具：让模型自己拆解任务并跟踪进度。

两个工具配合使用：

- ``create_plan``：把任务拆成有序步骤
- ``update_plan_step``：标记某一步进行中 / 已完成

工具本身不持有状态，计划存在 :mod:`agentos.runtime.planning` 的
``contextvars`` 里，因此天然按运行隔离。
"""

from __future__ import annotations

from agentos.runtime.planning import StepStatus, build_plan, get_plan, set_plan
from agentos.runtime.tools import Tool

MAX_STEPS = 12


class CreatePlanTool(Tool):
    """创建一个执行计划。"""

    name = "create_plan"
    description = (
        "为一个需要多步完成的任务创建执行计划（步骤清单）。"
        "创建后应逐步执行，并用 update_plan_step 更新每一步的状态。"
        "简单问答或单步任务不要使用本工具。"
    )
    category = "planning"
    risk_level = "low"
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "这次任务的总体目标，一句话概括"},
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "按执行顺序排列的步骤，每条一句话，建议 2-6 步，最多 12 步",
            },
        },
        "required": ["goal", "steps"],
    }

    async def run(self, goal: str, steps: list[str]) -> str:
        cleaned = [item.strip() for item in steps if isinstance(item, str) and item.strip()]
        if not cleaned:
            return "创建失败：steps 不能为空。"
        if len(cleaned) > MAX_STEPS:
            cleaned = cleaned[:MAX_STEPS]

        plan = build_plan(goal, cleaned)
        set_plan(plan)
        return f"计划已创建。\n{plan.render()}"


class UpdatePlanStepTool(Tool):
    """更新计划步骤状态。"""

    name = "update_plan_step"
    description = (
        "更新执行计划中某一步的状态：开始做时标记 in_progress，做完标记 completed。"
        "每完成一步都应调用一次，便于跟踪进度。"
    )
    category = "planning"
    risk_level = "low"
    parameters = {
        "type": "object",
        "properties": {
            "step_id": {
                "type": "integer",
                "description": "步骤编号，从 1 开始，对应 create_plan 中步骤的顺序",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
                "description": "新的状态",
            },
        },
        "required": ["step_id", "status"],
    }

    async def run(self, step_id: int, status: str) -> str:
        plan = get_plan()
        if plan is None:
            return "当前还没有执行计划，请先调用 create_plan。"

        step = plan.find(step_id)
        if step is None:
            available = "、".join(str(item.id) for item in plan.steps)
            return f"步骤 {step_id} 不存在，可用编号：{available}"

        try:
            step.status = StepStatus(status)
        except ValueError:
            return f"无效状态：{status}"

        suffix = "全部步骤已完成。" if plan.is_done else ""
        return f"已更新步骤 {step_id}。\n{plan.render()}\n{suffix}".rstrip()


def create_plan_tools() -> list[Tool]:
    """创建计划相关工具。"""
    return [CreatePlanTool(), UpdatePlanStepTool()]
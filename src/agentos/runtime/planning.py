"""执行计划（Planning）。

Planning 让 Agent **动手前先拆解任务**，并在执行过程中跟踪进度。

实现方式是一个「运行期计划」：

1. 模型通过 ``create_plan`` 工具生成步骤列表
2. 每完成一步，用 ``update_plan_step`` 更新状态
3. Runtime 在每一轮调用模型前，把当前计划并入系统提示词，
   让模型始终看得到自己的计划与进度

计划存放在 :mod:`contextvars` 里，因此**天然按运行隔离**：
并发运行互不干扰，运行结束自动丢弃，不需要额外清理。
这一点和 ``request_id`` / ``run_id`` 的做法一致。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from enum import StrEnum

from pydantic import BaseModel, Field


class StepStatus(StrEnum):
    """计划步骤状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class PlanStep(BaseModel):
    """计划中的一个步骤。"""

    id: int
    description: str
    status: StepStatus = StepStatus.PENDING

    def render(self) -> str:
        """渲染成一行提示词。"""
        marker = {
            StepStatus.PENDING: "[ ]",
            StepStatus.IN_PROGRESS: "[~]",
            StepStatus.COMPLETED: "[x]",
        }[self.status]
        return f"{marker} {self.id}. {self.description}"


class ExecutionPlan(BaseModel):
    """一次运行的执行计划。"""

    goal: str = ""
    steps: list[PlanStep] = Field(default_factory=list)

    @property
    def completed(self) -> int:
        """已完成步骤数。"""
        return sum(1 for step in self.steps if step.status == StepStatus.COMPLETED)

    @property
    def is_done(self) -> bool:
        """是否全部完成。"""
        return bool(self.steps) and self.completed == len(self.steps)

    def find(self, step_id: int) -> PlanStep | None:
        """按 id 查找步骤。"""
        return next((step for step in self.steps if step.id == step_id), None)

    def render(self) -> str:
        """渲染为可注入系统提示词的文本。"""
        lines = ["[执行计划]"]
        if self.goal:
            lines.append(f"目标：{self.goal}")
        lines.extend(step.render() for step in self.steps)
        lines.append(f"进度：{self.completed}/{len(self.steps)} 已完成")
        return "\n".join(lines)


_current_plan: ContextVar[ExecutionPlan | None] = ContextVar(
    "agentos_execution_plan", default=None
)


def get_plan() -> ExecutionPlan | None:
    """返回当前运行的执行计划。"""
    return _current_plan.get()


def set_plan(plan: ExecutionPlan | None) -> Token[ExecutionPlan | None]:
    """设置当前运行的执行计划。"""
    return _current_plan.set(plan)


def reset_plan(token: Token[ExecutionPlan | None]) -> None:
    """恢复上一个执行计划（用于运行结束时还原上下文）。"""
    _current_plan.reset(token)


def build_plan(goal: str, steps: list[str]) -> ExecutionPlan:
    """根据目标与步骤描述创建计划。"""
    return ExecutionPlan(
        goal=goal.strip(),
        steps=[
            PlanStep(id=index, description=description.strip())
            for index, description in enumerate(steps, start=1)
            if description.strip()
        ],
    )
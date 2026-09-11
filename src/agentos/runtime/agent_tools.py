"""多 Agent 协作：把子任务委托给其他已注册的 Agent。

实现方式是**把 Agent 暴露成工具**：主 Agent 通过 ``delegate_to_agent``
把子任务交给某个专门角色（例如让 ``researcher`` 做检索、让 ``reviewer`` 做审查），
拿到结果后继续自己的推理。这就是最小可用的「消息路由」。

两条重要的约束：

- **深度限制**：委托链最多 ``max_depth`` 层，防止 A → B → A 无限递归。
  深度存在 ``contextvars`` 里，因此并发运行各自独立计数。
- **子 Agent 无状态运行**：父 Agent 必须给出自包含的任务描述；
  子 Agent 不读写父级的会话记忆，避免两个上下文互相污染。
"""

from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar
from typing import TYPE_CHECKING

from agentos.core.context import get_agent_name
from agentos.core.exceptions import AgentOSError
from agentos.llm.base import ToolSpec
from agentos.runtime.tools import Tool

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注，避免循环导入
    from agentos.runtime.runtime import AgentRuntime

DEFAULT_MAX_DEPTH = 3

_delegation_depth: ContextVar[int] = ContextVar("agentos_delegation_depth", default=0)


def current_delegation_depth() -> int:
    """返回当前委托深度（用于测试与观测）。"""
    return _delegation_depth.get()


class DelegateToAgentTool(Tool):
    """把子任务交给另一个 Agent 执行。"""

    name = "delegate_to_agent"
    description = (
        "把子任务委托给另一个已注册的 Agent 执行，并返回它的结果。"
        "适合把不同领域的子任务分派给专门角色。"
        "委托出去的任务必须**自包含**：子 Agent 看不到当前对话的历史。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "目标 Agent 名称"},
            "task": {
                "type": "string",
                "description": "交给它的完整任务描述，需要自包含",
            },
        },
        "required": ["agent", "task"],
    }

    def __init__(
        self, runtime: AgentRuntime, *, max_depth: int = DEFAULT_MAX_DEPTH
    ) -> None:
        self._runtime = runtime
        self._max_depth = max(1, max_depth)

    def spec(self) -> ToolSpec:
        """动态声明可用 Agent —— 名称随注册表变化，不能写死在类属性里。"""
        names = [agent.name for agent in self._runtime.registry.list()]
        description = self.description
        if names:
            description = f"{description}\n当前可用的 Agent：{'、'.join(names)}。"
        return ToolSpec(name=self.name, description=description, parameters=self.parameters)

    async def run(self, agent: str, task: str) -> str:
        if not task.strip():
            return "委托失败：task 不能为空。"

        current = get_agent_name()
        if agent == current:
            return f"不能把任务委托给当前 Agent 自己（{agent}），请直接完成。"

        depth = _delegation_depth.get()
        if depth >= self._max_depth:
            return f"已达到最大委托深度 {self._max_depth}，请自行完成剩余任务。"

        if agent not in self._runtime.registry:
            available = "、".join(item.name for item in self._runtime.registry.list())
            return f"Agent 不存在：{agent}。可用：{available}"

        token = _delegation_depth.set(depth + 1)
        try:
            result = await self._runtime.run(agent, task, stateless=True)
        except AgentOSError as exc:
            return f"委托失败：{exc.message}"
        finally:
            _delegation_depth.reset(token)

        return f"[{agent} 的回复]\n{result.output}"


def create_agent_tools(
    runtime: AgentRuntime, *, max_depth: int = DEFAULT_MAX_DEPTH
) -> Sequence[Tool]:
    """创建多 Agent 协作工具。"""
    return [DelegateToAgentTool(runtime, max_depth=max_depth)]
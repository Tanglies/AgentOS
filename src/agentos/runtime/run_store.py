"""运行记录持久化与历史查询。

每次 Agent 运行结束后把结果落盘，解决「跑完就查不到」的问题 ——
在此之前 ``run_id`` 只存在于日志里，没有任何接口能回看某次运行做了什么。

数据访问委托给 :class:`~agentos.runtime.repositories.RunRepository`，
本模块只负责业务语义：把 ``RunResult`` 转成记录、容量淘汰、列表裁剪。

.. note::

   ``RunStatus`` / ``RunRecord`` / ``RunAggregate`` 从 repositories 重新导出，
   保证既有的 ``from agentos.runtime.run_store import RunRecord`` 仍然可用。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentos.core.config import RunStoreSettings
from agentos.core.context import get_user_id, get_workspace_id
from agentos.core.exceptions import NotFoundError
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.database.connection import Database
from agentos.runtime.repositories import (
    RUNS_SCHEMA,
    RunAggregate,
    RunRecord,
    RunRepository,
    RunStatus,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注，避免与 runtime 循环导入
    from agentos.runtime.runtime import RunResult

MAX_INPUT_CHARS = 4000

__all__ = ["MAX_INPUT_CHARS", "RunAggregate", "RunRecord", "RunStatus", "RunStore"]


def _as_status(value: RunStatus | str | None) -> RunStatus | None:
    """宽容地把字符串转成 ``RunStatus``（HTTP 查询参数是字符串）。"""
    if value is None or isinstance(value, RunStatus):
        return value
    try:
        return RunStatus(value)
    except ValueError:
        return None


class RunStore:
    """运行记录存储。"""

    def __init__(self, settings: RunStoreSettings | None = None) -> None:
        self._settings = settings or RunStoreSettings()
        self.path = Path(self._settings.db_path).expanduser()
        self._db = Database(self.path, schema=RUNS_SCHEMA)
        self._repo = RunRepository(self._db)

    @staticmethod
    def _scope(workspace_id: int | None = None) -> int:
        return workspace_id or get_workspace_id() or DEFAULT_WORKSPACE_ID

    @property
    def repository(self) -> RunRepository:
        """底层 Repository，供 Evaluation 等只读查询直接使用。"""
        return self._repo

    def record(self, result: RunResult, *, input_text: str = "") -> RunRecord:
        """记录一次成功的运行。"""
        usage = result.usage
        record = RunRecord(
            run_id=result.run_id,
            workspace_id=result.workspace_id,
            user_id=result.user_id,
            agent=result.agent,
            session_id=result.session_id,
            status=RunStatus.COMPLETED,
            input=input_text[:MAX_INPUT_CHARS],
            output=result.output,
            iterations=result.iterations,
            duration_ms=result.duration_ms,
            tool_call_count=result.tool_call_count,
            finish_reason=result.finish_reason,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            tool_error_count=result.tool_error_count,
            tool_timeout_count=result.tool_timeout_count,
            llm_call_count=result.llm_call_count,
            llm_error_count=result.llm_error_count,
            memory_recall_count=result.memory_recall_count,
            memory_context_chars=result.memory_context_chars,
            estimated_cost=result.estimated_cost,
            max_iterations_reached=result.max_iterations_reached,
            messages=list(result.messages),
        )
        self._repo.add(record)
        self._repo.prune(
            self._settings.max_records, workspace_id=record.workspace_id
        )
        return record

    def record_failure(
        self,
        *,
        run_id: str,
        agent: str,
        input_text: str,
        error: str,
        session_id: str | None = None,
        duration_ms: float = 0.0,
        workspace_id: int | None = None,
        user_id: int | None = None,
        tool_error_count: int = 0,
        tool_timeout_count: int = 0,
        llm_call_count: int = 0,
        llm_error_count: int = 0,
        memory_recall_count: int = 0,
        memory_context_chars: int = 0,
        estimated_cost: float | None = None,
        max_iterations_reached: bool = False,
    ) -> RunRecord:
        """记录一次失败的运行 —— 失败同样值得留痕，便于排查。"""
        scope = self._scope(workspace_id)
        record = RunRecord(
            run_id=run_id,
            workspace_id=scope,
            user_id=user_id if user_id is not None else get_user_id(),
            agent=agent,
            session_id=session_id,
            status=RunStatus.FAILED,
            input=input_text[:MAX_INPUT_CHARS],
            error=error,
            duration_ms=duration_ms,
            tool_error_count=tool_error_count,
            tool_timeout_count=tool_timeout_count,
            llm_call_count=llm_call_count,
            llm_error_count=llm_error_count,
            memory_recall_count=memory_recall_count,
            memory_context_chars=memory_context_chars,
            estimated_cost=estimated_cost,
            max_iterations_reached=max_iterations_reached,
        )
        self._repo.add(record)
        self._repo.prune(self._settings.max_records, workspace_id=scope)
        return record

    def record_cancelled(
        self,
        *,
        run_id: str,
        agent: str,
        input_text: str,
        session_id: str | None = None,
        duration_ms: float = 0.0,
        workspace_id: int | None = None,
        user_id: int | None = None,
        tool_error_count: int = 0,
        tool_timeout_count: int = 0,
        llm_call_count: int = 0,
        llm_error_count: int = 0,
        memory_recall_count: int = 0,
        memory_context_chars: int = 0,
        estimated_cost: float | None = None,
    ) -> RunRecord:
        """Record a run cancelled because the client disconnected."""
        scope = self._scope(workspace_id)
        record = RunRecord(
            run_id=run_id,
            workspace_id=scope,
            user_id=user_id if user_id is not None else get_user_id(),
            agent=agent,
            session_id=session_id,
            status=RunStatus.CANCELLED,
            input=input_text[:MAX_INPUT_CHARS],
            error="cancelled",
            duration_ms=duration_ms,
            tool_error_count=tool_error_count,
            tool_timeout_count=tool_timeout_count,
            llm_call_count=llm_call_count,
            llm_error_count=llm_error_count,
            memory_recall_count=memory_recall_count,
            memory_context_chars=memory_context_chars,
            estimated_cost=estimated_cost,
        )
        self._repo.add(record)
        self._repo.prune(self._settings.max_records, workspace_id=scope)
        return record

    def get(
        self, run_id: str, *, workspace_id: int | None = None
    ) -> RunRecord:
        """按 run_id 和 Workspace 取一条完整记录。"""
        scope = self._scope(workspace_id)
        record = self._repo.get(run_id, workspace_id=scope)
        if record is None:
            raise NotFoundError(f"run not found: {run_id}", details={"run_id": run_id})
        return record

    def list(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        status: RunStatus | str | None = None,
        workspace_id: int | None = None,
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[RunRecord]:
        """按条件查询历史运行，默认最新在前。

        ``order="asc"`` 改为最早在前。返回的记录**不含消息列表**，
        避免列表接口把上下文撑爆；需要完整轨迹请用 :meth:`get`。
        """
        records = self._repo.list(
            workspace_id=self._scope(workspace_id),
            agent=agent,
            session_id=session_id,
            status=_as_status(status),
            order=order,
            limit=limit,
            offset=offset,
        )
        return [record.model_copy(update={"messages": []}) for record in records]

    def count(
        self,
        *,
        agent: str | None = None,
        session_id: str | None = None,
        status: RunStatus | str | None = None,
        workspace_id: int | None = None,
    ) -> int:
        """满足条件的记录总数（分页用）。"""
        return self._repo.count(
            workspace_id=self._scope(workspace_id),
            agent=agent,
            session_id=session_id,
            status=_as_status(status),
        )

    def clear(self, *, workspace_id: int | None = None) -> int:
        """清空当前 Workspace 的记录。"""
        return self._repo.clear(workspace_id=self._scope(workspace_id))
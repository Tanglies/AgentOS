"""评估指标路由。

基于运行记录给出延迟、token 用量、成功率与工具调用统计。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from agentos.api.deps import RuntimeDep, require
from agentos.core.exceptions import NotFoundError
from agentos.runtime.api_keys import Permission
from agentos.runtime.evaluation import EvaluationSummary, Evaluator

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


def _require_evaluator(runtime: RuntimeDep) -> Evaluator:
    """运行记录关闭时给出明确错误，而不是返回一堆零。"""
    store = runtime.runs
    if store is None:
        raise NotFoundError(
            "evaluation requires run history",
            details={"hint": "set AGENTOS_RUNS__ENABLED=true"},
        )
    return Evaluator(store.repository)


@router.get(
    "/summary",
    response_model=EvaluationSummary,
    summary="评估指标汇总",
    dependencies=[require(Permission.EVALUATION_READ)],
)
async def get_summary(
    runtime: RuntimeDep,
    agent: Annotated[str | None, Query(description="只统计某个 Agent")] = None,
    since: Annotated[datetime | None, Query(description="只统计该时间之后")] = None,
) -> EvaluationSummary:
    """返回延迟、token、成功率与工具调用的聚合指标。"""
    return _require_evaluator(runtime).summarize(agent=agent, since=since)

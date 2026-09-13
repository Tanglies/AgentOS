"""Evaluation 2.0 run management routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from agentos.api.deps import EvaluationServiceDep, require
from agentos.api.schemas import (
    EvaluationRunDetail,
    EvaluationRunListResponse,
    EvaluationRunRequest,
    EvaluationRunSummary,
)
from agentos.core.context import get_user_id, get_workspace_id
from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.runtime.api_keys import Permission

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post(
    "/run",
    response_model=EvaluationRunSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="启动数据集评测",
    dependencies=[require(Permission.EVALUATION_RUN)],
)
async def start_evaluation(
    payload: EvaluationRunRequest,
    service: EvaluationServiceDep,
) -> EvaluationRunSummary:
    """Create a queued Evaluation run and execute it in the background."""
    run = service.create_run(
        dataset_name=payload.dataset,
        workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID,
        user_id=get_user_id() or DEFAULT_USER_ID,
        config=payload.config,
    )
    return EvaluationRunSummary.from_run(run)


@router.get(
    "",
    response_model=EvaluationRunListResponse,
    summary="查询评测运行",
    dependencies=[require(Permission.EVALUATION_READ)],
)
async def list_evaluations(
    service: EvaluationServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvaluationRunListResponse:
    runs, total = service.list(limit=limit, offset=offset)
    return EvaluationRunListResponse(
        items=[EvaluationRunSummary.from_run(run) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{run_id}",
    response_model=EvaluationRunDetail,
    summary="查看评测运行详情",
    dependencies=[require(Permission.EVALUATION_READ)],
)
async def get_evaluation(
    run_id: str, service: EvaluationServiceDep
) -> EvaluationRunDetail:
    return EvaluationRunDetail.from_run(service.get(run_id))

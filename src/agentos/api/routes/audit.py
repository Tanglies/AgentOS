"""审计日志路由。

审计记录面向追责：谁、什么时候、对什么做了什么、结果如何。
与运行记录的区别是字段固定、量小、需要长期保留。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from agentos.api.deps import RuntimeDep, require
from agentos.core.exceptions import NotFoundError
from agentos.runtime.api_keys import Permission
from agentos.runtime.repositories import AuditEntry, AuditStatus

router = APIRouter(prefix="/audit", tags=["audit"])


def _require_audit(runtime: RuntimeDep):
    """审计关闭时给出明确错误，而不是返回空列表让人误以为没有操作。"""
    audit = runtime.audit
    if audit is None:
        raise NotFoundError(
            "audit log is disabled", details={"hint": "set AGENTOS_AUDIT__ENABLED=true"}
        )
    return audit


@router.get(
    "",
    response_model=list[AuditEntry],
    summary="查询审计日志",
    dependencies=[require(Permission.AUDIT_READ)],
)
async def list_audit(
    runtime: RuntimeDep,
    action: Annotated[str | None, Query(description="按动作过滤，如 agent.run")] = None,
    actor: Annotated[str | None, Query(description="按调用方密钥指纹过滤")] = None,
    run_id: Annotated[str | None, Query(description="按运行 ID 过滤")] = None,
    status: Annotated[AuditStatus | None, Query(description="按结果过滤")] = None,
    order: Annotated[str, Query(pattern="^(asc|desc)$", description="按时间排序")] = "desc",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEntry]:
    """按条件返回审计记录，默认最新在前。"""
    audit = _require_audit(runtime)
    return audit.list(
        action=action,
        actor=actor,
        run_id=run_id,
        status=status,
        order=order,
        limit=limit,
        offset=offset,
    )

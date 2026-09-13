"""Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response

from agentos.core.exceptions import NotFoundError
from agentos.observability.metrics import metrics_enabled, render_metrics

router = APIRouter(tags=["observability"])


@router.get("/metrics", summary="Prometheus 指标")
async def metrics() -> Response:
    """Return Prometheus text metrics when Prometheus is enabled."""
    if not metrics_enabled():
        raise NotFoundError(
            "prometheus metrics are disabled",
            details={"hint": "set AGENTOS_OBSERVABILITY__PROMETHEUS_ENABLED=true"},
        )
    return Response(content=render_metrics(), media_type="text/plain; version=0.0.4")

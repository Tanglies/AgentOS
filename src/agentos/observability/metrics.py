"""Prometheus metrics with explicit low-cardinality labels."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from agentos.core.config import ObservabilitySettings

_SETTINGS = ObservabilitySettings()
_REGISTRY = CollectorRegistry()
_RUNS: Counter | None = None
_RUN_DURATION: Histogram | None = None
_RUN_ERRORS: Counter | None = None
_LLM_REQUESTS: Counter | None = None
_LLM_DURATION: Histogram | None = None
_LLM_TOKENS: Counter | None = None
_TOOL_CALLS: Counter | None = None
_TOOL_DURATION: Histogram | None = None
_TOOL_TIMEOUTS: Counter | None = None


def configure_metrics(settings: ObservabilitySettings) -> None:
    """Create metrics on a fresh registry according to settings."""
    global _SETTINGS, _REGISTRY, _RUNS, _RUN_DURATION, _RUN_ERRORS
    global _LLM_REQUESTS, _LLM_DURATION, _LLM_TOKENS, _TOOL_CALLS, _TOOL_DURATION
    global _TOOL_TIMEOUTS
    _SETTINGS = settings
    _REGISTRY = CollectorRegistry()
    if not settings.prometheus_enabled:
        _RUNS = _RUN_DURATION = _RUN_ERRORS = None
        _LLM_REQUESTS = _LLM_DURATION = _LLM_TOKENS = None
        _TOOL_CALLS = _TOOL_DURATION = _TOOL_TIMEOUTS = None
        return
    _RUNS = Counter("agentos_runs_total", "Agent runs", ["agent", "status"], registry=_REGISTRY)
    _RUN_DURATION = Histogram(
        "agentos_run_duration_seconds", "Agent run duration", ["agent"], registry=_REGISTRY
    )
    _RUN_ERRORS = Counter(
        "agentos_run_errors_total", "Agent run errors", ["agent", "error_type"], registry=_REGISTRY
    )
    _LLM_REQUESTS = Counter(
        "agentos_llm_requests_total", "LLM requests", ["model", "status"], registry=_REGISTRY
    )
    _LLM_DURATION = Histogram(
        "agentos_llm_duration_seconds", "LLM request duration", ["model"], registry=_REGISTRY
    )
    _LLM_TOKENS = Counter(
        "agentos_llm_tokens_total", "LLM tokens", ["model", "type"], registry=_REGISTRY
    )
    _TOOL_CALLS = Counter(
        "agentos_tool_calls_total", "Tool calls", ["tool", "status"], registry=_REGISTRY
    )
    _TOOL_DURATION = Histogram(
        "agentos_tool_duration_seconds", "Tool duration", ["tool"], registry=_REGISTRY
    )
    _TOOL_TIMEOUTS = Counter(
        "agentos_tool_timeouts_total", "Tool timeouts", ["tool"], registry=_REGISTRY
    )


def metrics_enabled() -> bool:
    return _SETTINGS.prometheus_enabled


def render_metrics() -> bytes:
    """Render the current registry in Prometheus text format."""
    return generate_latest(_REGISTRY)


def record_run(
    *,
    agent: str,
    status: str,
    duration_seconds: float,
    error_type: str | None = None,
    tool_call_count: int = 0,
    tool_error_count: int = 0,
    tool_timeout_count: int = 0,
    llm_call_count: int = 0,
    llm_error_count: int = 0,
    estimated_cost: float | None = None,
) -> None:
    del tool_call_count, tool_error_count, tool_timeout_count, llm_call_count
    del llm_error_count, estimated_cost
    if _RUNS is None or _RUN_DURATION is None:
        return
    _RUNS.labels(agent=agent, status=status).inc()
    _RUN_DURATION.labels(agent=agent).observe(max(0.0, duration_seconds))
    if error_type and _RUN_ERRORS is not None:
        _RUN_ERRORS.labels(agent=agent, error_type=error_type).inc()


def record_llm(
    *,
    model: str,
    status: str,
    duration_seconds: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    if _LLM_REQUESTS is None or _LLM_DURATION is None or _LLM_TOKENS is None:
        return
    _LLM_REQUESTS.labels(model=model, status=status).inc()
    _LLM_DURATION.labels(model=model).observe(max(0.0, duration_seconds))
    if prompt_tokens:
        _LLM_TOKENS.labels(model=model, type="prompt").inc(prompt_tokens)
    if completion_tokens:
        _LLM_TOKENS.labels(model=model, type="completion").inc(completion_tokens)


def record_tool(
    *,
    tool: str,
    status: str,
    duration_seconds: float,
    timeout: bool = False,
) -> None:
    if _TOOL_CALLS is None or _TOOL_DURATION is None:
        return
    _TOOL_CALLS.labels(tool=tool, status=status).inc()
    _TOOL_DURATION.labels(tool=tool).observe(max(0.0, duration_seconds))
    if timeout and _TOOL_TIMEOUTS is not None:
        _TOOL_TIMEOUTS.labels(tool=tool).inc()


__all__ = [
    "configure_metrics",
    "metrics_enabled",
    "record_llm",
    "record_run",
    "record_tool",
    "render_metrics",
]

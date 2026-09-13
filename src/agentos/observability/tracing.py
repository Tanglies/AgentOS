"""OpenTelemetry tracing setup and span helpers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Status, StatusCode

from agentos.core.config import ObservabilitySettings
from agentos.core.context import (
    get_otel_span_id,
    get_otel_trace_id,
    get_trace_id,
    reset_otel_span_id,
    reset_otel_trace_id,
    set_otel_span_id,
    set_otel_trace_id,
)

_tracer: trace.Tracer | None = None
_provider: TracerProvider | None = None
_settings = ObservabilitySettings()
_SENSITIVE_MARKERS = ("prompt", "api_key", "apikey", "secret", "memory", "content")


def configure_tracing(
    settings: ObservabilitySettings,
    *,
    span_exporter: SpanExporter | None = None,
) -> TracerProvider | None:
    """Configure tracing; disabled mode is a no-op."""
    global _tracer, _provider, _settings
    _settings = settings
    if not settings.enabled:
        _tracer = None
        _provider = None
        return None

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.service_name})
    )
    if span_exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(span_exporter))
    elif settings.export_traces and settings.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
        )
    _provider = provider
    _tracer = provider.get_tracer("agentos")
    return provider


def reset_tracing() -> None:
    """Reset tracing state, primarily for tests."""
    global _tracer, _provider
    _tracer = None
    _provider = None


def get_tracer() -> trace.Tracer | None:
    """Return the configured tracer, if any."""
    return _tracer


def current_otel_ids() -> tuple[str | None, str | None]:
    """Return the current OTel trace and span identifiers."""
    return get_otel_trace_id(), get_otel_span_id()


def force_flush(timeout_millis: int = 5000) -> None:
    """Flush the configured provider."""
    if _provider is not None:
        _provider.force_flush(timeout_millis)


@contextmanager
def start_span(
    name: str,
    *,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[Span | None]:
    """Start a span and bind its IDs into the request logging context."""
    tracer = _tracer
    if tracer is None:
        yield None
        return

    safe_attributes = _safe_attributes(attributes or {})
    trace_id = safe_attributes.get("agentos.trace_id") or get_trace_id()
    if trace_id:
        safe_attributes.setdefault("agentos.trace_id", trace_id)
    with tracer.start_as_current_span(name, attributes=safe_attributes) as span:
        span_context = span.get_span_context()
        trace_token = set_otel_trace_id(
            format(span_context.trace_id, "032x") if span_context.is_valid else None
        )
        span_token = set_otel_span_id(
            format(span_context.span_id, "016x") if span_context.is_valid else None
        )
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            reset_otel_span_id(span_token)
            reset_otel_trace_id(trace_token)


def set_span_attributes(span: Span | None, attributes: Mapping[str, Any]) -> None:
    """Add sanitized attributes to a span."""
    if span is None:
        return
    for key, value in _safe_attributes(attributes).items():
        span.set_attribute(key, value)


def _safe_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in attributes.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SENSITIVE_MARKERS):
            continue
        if isinstance(value, str | int | float | bool):
            safe[key] = value
        elif value is None:
            continue
        else:
            safe[key] = str(value)
    return safe


__all__ = [
    "configure_tracing",
    "current_otel_ids",
    "force_flush",
    "get_tracer",
    "reset_tracing",
    "set_span_attributes",
    "start_span",
]

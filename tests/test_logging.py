"""日志系统测试。"""

from __future__ import annotations

import json
import logging
from typing import Any

from agentos.core.config import LoggingSettings
from agentos.core.context import request_context
from agentos.core.logging import (
    ROOT_LOGGER_NAME,
    ConsoleFormatter,
    JsonFormatter,
    configure_logging,
    get_logger,
    redact,
)


def _make_record(message: str, **extra: Any) -> logging.LogRecord:
    record = logging.LogRecord(
        name="agentos.tests",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    if extra:
        record.extra_fields = extra  # type: ignore[attr-defined]
    return record


def test_json_formatter_outputs_structured_payload() -> None:
    formatter = JsonFormatter()

    payload = json.loads(formatter.format(_make_record("agent started", agent="assistant")))

    assert payload["message"] == "agent started"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "agentos.tests"
    assert payload["agent"] == "assistant"
    assert "timestamp" in payload


def test_json_formatter_includes_request_context() -> None:
    formatter = JsonFormatter()

    with request_context("req_test"):
        payload = json.loads(formatter.format(_make_record("with context")))

    assert payload["request_id"] == "req_test"


def test_formatter_redacts_sensitive_fields() -> None:
    formatter = JsonFormatter()
    record = _make_record(
        "secret",
        payload={"api_key": "sk-1", "nested": {"token": "t", "keep": "v"}},
        authorization="Bearer abc",
    )

    payload = json.loads(formatter.format(record))

    assert payload["payload"]["api_key"] == "***"
    assert payload["payload"]["nested"]["token"] == "***"
    assert payload["payload"]["nested"]["keep"] == "v"
    assert payload["authorization"] == "***"


def test_console_formatter_contains_context_and_extra() -> None:
    formatter = ConsoleFormatter()

    with request_context("req_console"):
        line = formatter.format(_make_record("boot", status="ok"))

    assert "boot" in line
    assert "request_id=req_console" in line
    assert "status=ok" in line


def test_redact_handles_nested_lists() -> None:
    result = redact({"items": [{"password": "p"}, {"safe": 1}]})

    assert result["items"][0]["password"] == "***"
    assert result["items"][1]["safe"] == 1


def test_configure_logging_is_idempotent_and_respects_level() -> None:
    first = configure_logging(LoggingSettings(level="DEBUG", format="json"), force=True)
    handler_count = len(first.handlers)

    second = configure_logging(LoggingSettings(level="WARNING", format="json"))

    assert second is first
    assert len(second.handlers) == handler_count == 1
    assert second.level == logging.WARNING
    assert second.propagate is False


def test_get_logger_namespaces_names() -> None:
    assert get_logger().name == ROOT_LOGGER_NAME
    assert get_logger("agentos.runtime").name == "agentos.runtime"
    assert get_logger("runtime.runner").name == "agentos.runtime.runner"
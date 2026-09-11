"""结构化日志系统。

设计要点：

- 只依赖标准库 :mod:`logging`，不引入额外运行时依赖
- 支持 ``console``（人类可读）与 ``json``（机器采集）两种格式
- 自动附加 request_id / run_id 等上下文
- 对 api_key、authorization 等敏感字段做脱敏
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from agentos.core.config import LoggingSettings
from agentos.core.context import current_context

ROOT_LOGGER_NAME = "agentos"
MASK = "***"
DEFAULT_REDACT_KEYS: frozenset[str] = frozenset(
    {"api_key", "authorization", "password", "secret", "token"}
)


def get_logger(name: str | None = None) -> logging.Logger:
    """获取 AgentOS 命名空间下的 logger。"""
    if not name or name == ROOT_LOGGER_NAME:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if name.startswith(f"{ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def redact(
    payload: Mapping[str, Any],
    *,
    keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """递归脱敏：命中 keys 的字段值被替换为 ``***``（大小写不敏感）。"""
    key_set = {key.lower() for key in (keys if keys is not None else DEFAULT_REDACT_KEYS)}

    def _clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(k): (MASK if str(k).lower() in key_set else _clean(v)) for k, v in value.items()
            }
        if isinstance(value, list | tuple):
            return [_clean(item) for item in value]
        return value

    return cast("dict[str, Any]", _clean(payload))


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    extra = getattr(record, "extra_fields", None)
    return dict(extra) if isinstance(extra, Mapping) else {}


def _log_payload(record: logging.LogRecord, redact_keys: Iterable[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
    }
    payload.update(current_context())
    payload.update(redact(_extra_fields(record), keys=redact_keys))
    return payload


class ContextFilter(logging.Filter):
    """把 contextvars 中的字段注入日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in current_context().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    """JSON 行格式，便于日志采集系统解析。"""

    def __init__(self, *, redact_keys: Iterable[str] = DEFAULT_REDACT_KEYS) -> None:
        super().__init__()
        self._redact_keys = tuple(redact_keys)

    def format(self, record: logging.LogRecord) -> str:
        payload = _log_payload(record, self._redact_keys)
        payload["timestamp"] = datetime.fromtimestamp(
            record.created, tz=UTC
        ).isoformat(timespec="milliseconds")
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """面向开发者的单行文本格式。"""

    def __init__(self, *, redact_keys: Iterable[str] = DEFAULT_REDACT_KEYS) -> None:
        super().__init__()
        self._redact_keys = tuple(redact_keys)

    def format(self, record: logging.LogRecord) -> str:
        payload = _log_payload(record, self._redact_keys)
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        level = payload.pop("level")
        name = payload.pop("logger")
        message = payload.pop("message")
        head = f"{timestamp} {level:<7} {name} - {message}"
        if payload:
            head += " | " + " ".join(f"{key}={value}" for key, value in payload.items())
        if record.exc_info:
            head += "\n" + self.formatException(record.exc_info)
        return head


def configure_logging(settings: LoggingSettings, *, force: bool = False) -> logging.Logger:
    """配置 AgentOS 根 logger。

    重复调用是幂等的：除非 ``force=True``，否则只刷新日志级别，不会重复添加 handler。
    """
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    level = logging.getLevelNamesMapping()[settings.level]

    if logger.handlers and not force:
        logger.setLevel(level)
        return logger

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter: logging.Formatter
    if settings.format == "json":
        formatter = JsonFormatter(redact_keys=settings.redact_keys)
    else:
        formatter = ConsoleFormatter(redact_keys=settings.redact_keys)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter())

    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
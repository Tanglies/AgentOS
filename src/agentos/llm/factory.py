"""LLM 客户端工厂。

通过注册表解耦「配置中的 provider 名称」与「具体实现」，
新增模型服务时只需实现 :class:`~agentos.llm.base.LLMClient` 并调用 :func:`register_provider`。
"""

from __future__ import annotations

from collections.abc import Callable

from agentos.core.config import LLMSettings, get_settings
from agentos.core.exceptions import ConfigurationError
from agentos.llm.base import LLMClient
from agentos.llm.echo import EchoLLMClient
from agentos.llm.openai_compatible import OpenAICompatibleLLMClient

LLMFactory = Callable[[LLMSettings], LLMClient]

_REGISTRY: dict[str, LLMFactory] = {}


def register_provider(name: str, factory: LLMFactory, *, overwrite: bool = False) -> None:
    """注册一个 LLM provider 工厂。"""
    key = name.strip().lower()
    if not key:
        raise ConfigurationError("provider name must not be empty")
    if key in _REGISTRY and not overwrite:
        raise ConfigurationError(
            f"LLM provider already registered: {key}", details={"provider": key}
        )
    _REGISTRY[key] = factory


def available_providers() -> tuple[str, ...]:
    """返回已注册的 provider 名称。"""
    return tuple(sorted(_REGISTRY))


def create_llm_client(settings: LLMSettings | None = None) -> LLMClient:
    """按配置创建 LLM 客户端。"""
    resolved = settings if settings is not None else get_settings().llm
    name = resolved.provider.strip().lower()
    factory = _REGISTRY.get(name)
    if factory is None:
        raise ConfigurationError(
            f"unknown LLM provider: {resolved.provider}",
            details={"available_providers": list(available_providers())},
        )
    return factory(resolved)


def _build_echo(settings: LLMSettings) -> LLMClient:
    """echo 客户端使用固定模型名，不消费 settings.model。"""
    return EchoLLMClient()


def _build_openai_compatible(settings: LLMSettings) -> LLMClient:
    return OpenAICompatibleLLMClient(
        base_url=settings.base_url,
        model=settings.model,
        api_key=settings.api_key.get_secret_value() if settings.api_key else None,
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
        default_temperature=settings.temperature,
        default_max_tokens=settings.max_tokens,
    )


register_provider("echo", _build_echo, overwrite=True)
register_provider("openai_compatible", _build_openai_compatible, overwrite=True)
register_provider("openai", _build_openai_compatible, overwrite=True)
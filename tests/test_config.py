"""配置管理测试。"""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from pydantic import ValidationError as PydanticValidationError

from agentos.core.config import Settings, get_settings, reset_settings_cache


def test_default_settings_are_local_and_safe() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_name == "AgentOS"
    assert settings.environment == "local"
    assert settings.is_production is False
    assert settings.llm.provider == "echo"
    assert settings.logging.level == "INFO"
    assert settings.api.port == 8000


def test_nested_env_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTOS_ENVIRONMENT", "production")
    monkeypatch.setenv("AGENTOS_LLM__PROVIDER", "openai_compatible")
    monkeypatch.setenv("AGENTOS_LLM__MODEL", "deepseek-chat")
    monkeypatch.setenv("AGENTOS_API__PORT", "9001")
    monkeypatch.setenv("AGENTOS_LOGGING__FORMAT", "json")

    settings = Settings(_env_file=None)

    assert settings.environment == "production"
    assert settings.is_production is True
    assert settings.llm.provider == "openai_compatible"
    assert settings.llm.model == "deepseek-chat"
    assert settings.api.port == 9001
    assert settings.logging.format == "json"


def test_log_level_is_normalized() -> None:
    settings = Settings(_env_file=None, logging={"level": "debug"})
    assert settings.logging.level == "DEBUG"


def test_api_key_is_a_secret() -> None:
    settings = Settings(_env_file=None, llm={"api_key": "sk-super-secret"})
    assert isinstance(settings.llm.api_key, SecretStr)
    assert settings.llm.api_key.get_secret_value() == "sk-super-secret"
    assert "sk-super-secret" not in settings.model_dump_json()


@pytest.mark.parametrize(
    "payload",
    [
        {"environment": "prod"},
        {"logging": {"level": "LOUD"}},
        {"api": {"port": 0}},
        {"llm": {"max_retries": 99}},
    ],
)
def test_invalid_settings_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, **payload)


def test_get_settings_is_cached_and_resettable(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("AGENTOS_APP_NAME", "Cached")
    first = get_settings()
    monkeypatch.setenv("AGENTOS_APP_NAME", "Changed")

    assert get_settings() is first
    assert get_settings().app_name == "Cached"

    reset_settings_cache()
    assert get_settings().app_name == "Changed"
"""应用配置管理。

配置来源优先级（高到低）：

1. 环境变量：前缀 ``AGENTOS_``，嵌套字段用 ``__`` 分隔，
   例如 ``AGENTOS_LLM__PROVIDER=openai_compatible``
2. ``.env`` 文件（项目根目录，参考 ``.env.example``）
3. 代码中的默认值

复杂类型（如列表）在环境变量中需要用 JSON 表示，例如
``AGENTOS_API__CORS_ORIGINS=["http://localhost:3000"]``。
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "staging", "production"]
LogFormat = Literal["console", "json"]


class LoggingSettings(BaseModel):
    """日志配置。"""

    level: str = "INFO"
    format: LogFormat = "console"
    redact_keys: tuple[str, ...] = ("api_key", "authorization", "password", "secret", "token")

    @field_validator("level")
    @classmethod
    def _validate_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level: {value}")
        return normalized


class LLMSettings(BaseModel):
    """LLM 提供方配置。"""

    provider: str = "echo"
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)


class RuntimeSettings(BaseModel):
    """Agent Runtime 配置。"""

    default_agent: str = "assistant"
    max_iterations: int = Field(default=8, ge=1, le=64)
    system_prompt: str = "You are AgentOS, a helpful AI agent."


class APISettings(BaseModel):
    """HTTP 服务配置。"""

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    root_path: str = ""
    enable_docs: bool = True
    cors_origins: tuple[str, ...] = ()


class Settings(BaseSettings):
    """AgentOS 全局配置。"""

    model_config = SettingsConfigDict(
        env_prefix="AGENTOS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "AgentOS"
    environment: Environment = "local"
    debug: bool = False
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    api: APISettings = Field(default_factory=APISettings)

    @property
    def is_production(self) -> bool:
        """是否为生产环境。"""
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程内缓存的配置实例。"""
    return Settings()


def reset_settings_cache() -> None:
    """清空配置缓存，主要用于测试。"""
    get_settings.cache_clear()
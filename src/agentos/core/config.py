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


class RegistrySettings(BaseModel):
    """Agent 注册表持久化配置。

    **默认持久化**：Agent 定义落盘 SQLite，进程重启不再丢失。
    设为 ``False`` 可退回内存实现（测试与嵌入式场景用）。
    """

    persist: bool = True
    db_path: str = ".agentos/agents.db"


class PlatformSettings(BaseModel):
    """Multi-tenant platform metadata configuration."""

    db_path: str = ".agentos/platform.db"


class ObservabilitySettings(BaseModel):
    """OpenTelemetry and Prometheus configuration."""

    enabled: bool = False
    service_name: str = "agentos"
    otlp_endpoint: str | None = None
    export_traces: bool = False
    export_metrics: bool = False
    sample_ratio: float = Field(default=1.0, gt=0.0, le=1.0)
    prometheus_enabled: bool = False
    metrics_path: str = "/metrics"


class EvaluationSettings(BaseModel):
    """Evaluation 2.0 configuration."""

    db_path: str = ".agentos/evaluations.db"
    max_records: int = Field(default=1000, ge=1, le=100_000)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    dataset_root: str = "evals"
    judge_enabled: bool = False
    judge_model: str | None = None


class QuotaSettings(BaseModel):
    """Default Workspace quotas and per-request rate limits."""

    daily_run_limit: int = Field(default=1000, ge=1)
    daily_token_limit: int = Field(default=1_000_000, ge=1)
    requests_per_minute: int = Field(default=60, ge=1)
    max_iterations_per_run: int = Field(default=8, ge=1, le=64)
    max_tool_calls_per_run: int = Field(default=10, ge=1, le=1000)


class ApiKeySettings(BaseModel):
    """API Key 存储配置。

    数据库只存密钥的 SHA-256 哈希，明文只在签发时返回一次。
    ``AGENTOS_AUTH__API_KEYS`` 里的静态密钥视为管理员（拥有全部权限），
    用于签发数据库密钥，解决「数据库里一把钥匙都没有」的引导问题。
    """

    enabled: bool = True
    db_path: str = ".agentos/api_keys.db"


class AuditSettings(BaseModel):
    """审计日志配置。

    与运行记录分开存：运行记录面向排查（量大、含完整消息轨迹），
    审计面向追责（量小、字段固定、需要长期保留）。
    """

    enabled: bool = True
    db_path: str = ".agentos/audit.db"
    max_records: int = Field(default=20_000, ge=1, le=1_000_000)


class RunStoreSettings(BaseModel):
    """运行记录持久化配置。

    默认开启：运行历史是排查问题的主要依据，落盘才有意义。
    数据库位于 ``.agentos/``，已被 ``.gitignore`` 忽略。
    记录保留最近 ``max_records`` 条，超出后淘汰最旧的。
    """

    enabled: bool = True
    db_path: str = ".agentos/runs.db"
    max_records: int = Field(default=10_000, ge=1, le=1_000_000)


class AuthSettings(BaseModel):
    """API 认证配置。

    默认**关闭**以方便本地开发；一旦对外暴露就必须开启并配置至少一个密钥。
    开启但没有配置任何密钥时会**拒绝所有请求**（fail closed），
    而不是退化成不校验 —— 配置失误不应该变成安全漏洞。
    """

    enabled: bool = False
    api_keys: tuple[SecretStr, ...] = ()
    header_name: str = "X-API-Key"
    public_paths: tuple[str, ...] = (
        "/health",
        "/health/ready",
        "/docs",
        "/redoc",
        "/openapi.json",
    )


class MemorySettings(BaseModel):
    """会话记忆配置。

    当前实现是进程内短期记忆：按 ``session_id`` 保存最近若干轮对话。
    会话数超过 ``max_sessions`` 时按 LRU 淘汰最久未使用的会话。

    ``long_term_*`` 控制长期记忆：默认落盘到 ``.agentos/memory.db``，
    跨会话保留，并在每次运行前按关键词召回相关条目注入上下文。

    ``default_session_id`` 是未显式传参时使用的会话：默认 ``default``，
    即记忆**开箱即用**；设置为空字符串可恢复「不传即无状态」的行为。
    """

    default_session_id: str = "default"
    max_messages_per_session: int = Field(default=50, ge=1, le=1000)
    max_sessions: int = Field(default=1000, ge=1, le=100_000)

    # 长期记忆：跨会话持久化到 SQLite，并按关键词检索召回
    long_term_enabled: bool = True
    long_term_db_path: str = ".agentos/memory.db"
    long_term_auto_recall: bool = True
    long_term_recall_limit: int = Field(default=5, ge=1, le=20)


class ToolsSettings(BaseModel):
    """本地工具（文件 / 命令）与联网工具配置。

    这些配置决定 Agent 能在多大范围内操作宿主机：

    - ``workspace_root``：所有文件工具的沙箱根目录，越界路径直接拒绝
    - ``allow_file_write``：是否允许写文件（覆盖已有文件还需显式确认）
    - ``allow_shell``：是否允许执行 shell 命令，**默认关闭**

    联网相关：``fetch_url`` 始终可用（受 SSRF 防护约束）；
    ``web_search`` 仅在配置了 ``web_search_api_key`` 时注册。
    """

    workspace_root: str = "."
    allow_file_write: bool = True
    allow_shell: bool = False
    shell_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    max_read_bytes: int = Field(default=256_000, gt=0)
    max_output_chars: int = Field(default=16_000, gt=0)
    web_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    max_web_bytes: int = Field(default=512_000, gt=0)
    web_search_api_url: str = "https://api.tavily.com/search"
    web_search_api_key: SecretStr | None = None
    web_search_max_results: int = Field(default=5, ge=1, le=20)


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
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    platform: PlatformSettings = Field(default_factory=PlatformSettings)
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    quota: QuotaSettings = Field(default_factory=QuotaSettings)
    runs: RunStoreSettings = Field(default_factory=RunStoreSettings)
    audit: AuditSettings = Field(default_factory=AuditSettings)
    api_keys: ApiKeySettings = Field(default_factory=ApiKeySettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)

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

"""统一异常体系。

所有对外异常都继承 :class:`AgentOSError`，并携带稳定的 ``code`` 与 HTTP ``status_code``，
API 层据此转换为统一错误响应，避免异常细节直接泄漏到客户端。
"""

from __future__ import annotations

from typing import Any


class AgentOSError(Exception):
    """AgentOS 异常基类。"""

    code: str = "agentos_error"
    status_code: int = 500
    message: str = "AgentOS internal error"

    def __init__(
        self, message: str | None = None, *, details: dict[str, Any] | None = None
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """转换为 API 错误响应体。"""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ConfigurationError(AgentOSError):
    """配置缺失或非法。"""

    code = "configuration_error"
    status_code = 500
    message = "Invalid AgentOS configuration"


class ValidationError(AgentOSError):
    """业务层参数校验失败。"""

    code = "validation_error"
    status_code = 422
    message = "Request validation failed"


class NotFoundError(AgentOSError):
    """资源不存在。"""

    code = "not_found"
    status_code = 404
    message = "Resource not found"


class ConflictError(AgentOSError):
    """资源已存在或状态冲突。"""

    code = "conflict"
    status_code = 409
    message = "Resource already exists"


class PermissionDeniedError(AgentOSError):
    """调用方没有执行该操作的权限。"""

    code = "permission_denied"
    status_code = 403
    message = "permission denied"


class LLMError(AgentOSError):
    """LLM 调用失败。"""

    code = "llm_error"
    status_code = 502
    message = "LLM request failed"


class LLMProviderError(LLMError):
    """上游模型服务返回错误。"""

    code = "llm_provider_error"
    message = "LLM provider returned an error"


class LLMTimeoutError(LLMError):
    """LLM 调用超时。"""

    code = "llm_timeout"
    status_code = 504
    message = "LLM request timed out"


class AgentRuntimeError(AgentOSError):
    """Agent 运行期错误。"""

    code = "agent_runtime_error"
    message = "Agent runtime failed"
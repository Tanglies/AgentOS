"""FastAPI 依赖注入。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from agentos.core.config import Settings
from agentos.llm.base import LLMClient
from agentos.runtime.runtime import AgentRuntime


def get_app_settings(request: Request) -> Settings:
    """从应用状态读取配置。"""
    return request.app.state.settings


def get_runtime(request: Request) -> AgentRuntime:
    """从应用状态读取 Agent Runtime。"""
    return request.app.state.runtime


def get_llm_client(request: Request) -> LLMClient:
    """从应用状态读取 LLM 客户端。"""
    return request.app.state.llm_client


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RuntimeDep = Annotated[AgentRuntime, Depends(get_runtime)]
LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
"""共享测试夹具。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.core.config import Settings, reset_settings_cache


@pytest.fixture(autouse=True)
def clean_agentos_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离宿主环境变量，保证测试只依赖代码中的默认值。"""
    for key in list(os.environ):
        if key.upper().startswith("AGENTOS_"):
            monkeypatch.delenv(key, raising=False)
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """测试用配置：本地环境、echo 提供方、JSON 日志、隔离的长期记忆库。

    长期记忆默认落盘到 ``.agentos/memory.db``，若不在测试中重定向，
    跑一次测试就会污染工作区，因此这里指向 ``tmp_path``。
    """
    return Settings(
        _env_file=None,
        environment="local",
        debug=True,
        llm={"provider": "echo"},
        logging={"level": "INFO", "format": "json"},
        memory={"long_term_db_path": str(tmp_path / "memory.db")},
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
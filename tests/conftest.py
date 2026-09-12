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


@pytest.fixture(autouse=True)
def isolate_data_paths(
    clean_agentos_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """把所有落盘路径重定向到 ``tmp_path``。

    有些测试会自己构造 ``Settings(_env_file=None, ...)`` 而不走 ``settings``
    夹具，如果只在夹具里重定向，那些用例仍会往工作区的 ``.agentos/`` 写数据。
    环境变量优先级最高，所以在这里统一设置，覆盖所有构造方式。

    依赖 ``clean_agentos_env`` 保证先清空、后设置，顺序不会颠倒。
    """
    monkeypatch.setenv("AGENTOS_RUNS__DB_PATH", str(tmp_path / "runs.db"))
    monkeypatch.setenv("AGENTOS_MEMORY__LONG_TERM_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("AGENTOS_REGISTRY__DB_PATH", str(tmp_path / "agents.db"))
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """测试用配置：本地环境、echo 提供方、JSON 日志、隔离的数据文件。

    长期记忆与运行记录默认落盘到 ``.agentos/``，若不在测试中重定向，
    跑一次测试就会往工作区写数据，因此这里统一指向 ``tmp_path``。
    """
    return Settings(
        _env_file=None,
        environment="local",
        debug=True,
        llm={"provider": "echo"},
        logging={"level": "INFO", "format": "json"},
        memory={"long_term_db_path": str(tmp_path / "memory.db")},
        runs={"db_path": str(tmp_path / "runs.db")},
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
"""Test harness configuration tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import pytest_configure


def test_pytest_configure_creates_basetemp_parent_for_clean_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = SimpleNamespace(option=SimpleNamespace(basetemp=None))

    pytest_configure(config)

    basetemp = Path(config.option.basetemp)
    assert basetemp.parent == Path(".pytest_tmp")
    assert basetemp.parent.is_dir()

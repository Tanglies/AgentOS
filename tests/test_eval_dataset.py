"""Evaluation dataset contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentos.core.exceptions import ValidationError
from agentos.evaluation import EvaluationCase, EvaluationDataset
from agentos.evaluation.dataset import load_jsonl, write_jsonl


def test_load_jsonl_dataset(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"id": "case-1", "name": "one", "input": "hello"}),
                json.dumps(
                    {
                        "id": "case-2",
                        "input": "calculate",
                        "expected_tools": ["calculate"],
                        "tags": ["tool_calling"],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    dataset = EvaluationDataset.from_jsonl(path)

    assert dataset.name == "cases"
    assert len(dataset.cases) == 2
    assert dataset.cases[1].expected_tools == ["calculate"]


def test_dataset_rejects_duplicate_case_id(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.jsonl"
    path.write_text(
        json.dumps({"id": "dup", "input": "a"})
        + "\n"
        + json.dumps({"id": "dup", "input": "b"})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_jsonl(path)


def test_dataset_rejects_invalid_line(tmp_path: Path) -> None:
    path = tmp_path / "invalid.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_jsonl(path)


def test_write_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "output.jsonl"
    cases = [EvaluationCase(id="a", input="hello")]

    write_jsonl(path, cases)

    assert load_jsonl(path)[0].id == "a"

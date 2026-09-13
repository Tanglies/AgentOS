"""JSONL Evaluation dataset loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

from agentos.core.exceptions import ValidationError
from agentos.evaluation.models import EvaluationCase


def load_jsonl(path: str | Path) -> list[EvaluationCase]:
    """Load and validate cases from a JSONL file."""
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise ValidationError(
            f"evaluation dataset not found: {resolved}",
            details={"path": str(resolved)},
        )

    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        resolved.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            case = EvaluationCase.model_validate(payload)
        except Exception as exc:
            raise ValidationError(
                f"invalid evaluation case at line {line_number}",
                details={"line": line_number, "error": str(exc)},
            ) from exc
        if case.id in seen:
            raise ValidationError(
                f"duplicate evaluation case id: {case.id}",
                details={"case_id": case.id, "line": line_number},
            )
        seen.add(case.id)
        cases.append(case)
    return cases


def write_jsonl(path: str | Path, cases: list[EvaluationCase]) -> None:
    """Write cases to JSONL for fixtures and benchmark generation."""
    resolved = Path(path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(case.model_dump(mode="json"), ensure_ascii=False)
        for case in cases
    ]
    resolved.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


__all__ = ["load_jsonl", "write_jsonl"]

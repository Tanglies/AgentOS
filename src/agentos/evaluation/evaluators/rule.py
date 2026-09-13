"""Metadata-driven rule evaluator."""

from __future__ import annotations

import re
from typing import Any

from agentos.evaluation.evaluators.base import Evaluator
from agentos.evaluation.evaluators.tool_call import extract_actual_tools
from agentos.evaluation.models import EvaluationCase, EvaluationScore
from agentos.runtime.runtime import RunResult


class RuleEvaluator(Evaluator):
    """Evaluate a list of declarative rules from ``case.metadata['rules']``."""

    name = "rule"

    async def evaluate(
        self, case: EvaluationCase, run_result: RunResult
    ) -> EvaluationScore:
        rules = case.metadata.get("rules", [])
        if not isinstance(rules, list) or not rules:
            return EvaluationScore(
                metric=self.name,
                score=1.0,
                passed=True,
                applicable=False,
                reason="no rules configured",
            )

        results: list[dict[str, Any]] = []
        for rule in rules:
            if not isinstance(rule, dict):
                results.append(
                    {"passed": False, "reason": "rule must be an object", "rule": rule}
                )
                continue
            results.append(self._apply(rule, run_result))
        passed_count = sum(1 for item in results if item["passed"])
        score = passed_count / len(results)
        return EvaluationScore(
            metric=self.name,
            score=round(score, 4),
            passed=passed_count == len(results),
            reason=f"{passed_count}/{len(results)} rules passed",
            metadata={"results": results},
        )

    @staticmethod
    def _apply(rule: dict[str, Any], run_result: RunResult) -> dict[str, Any]:
        kind = str(rule.get("type", "")).lower()
        value = rule.get("value")
        actual_tools = extract_actual_tools(run_result)
        if kind == "contains":
            passed = str(value or "") in run_result.output
        elif kind == "not_contains":
            passed = str(value or "") not in run_result.output
        elif kind == "equals":
            passed = run_result.output.strip() == str(value or "").strip()
        elif kind == "regex":
            passed = re.search(str(value or ""), run_result.output) is not None
        elif kind == "max_latency_ms":
            passed = run_result.duration_ms <= float(value)
        elif kind == "max_tokens":
            total = run_result.usage.total_tokens if run_result.usage else 0
            passed = total <= int(value)
        elif kind == "tool_called":
            passed = str(value) in actual_tools
        elif kind == "tool_not_called":
            passed = str(value) not in actual_tools
        else:
            passed = False
        return {
            "type": kind,
            "value": value,
            "passed": passed,
            "actual_tools": actual_tools,
        }


__all__ = ["RuleEvaluator"]

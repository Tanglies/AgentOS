"""评估指标（Evaluation）。

基于运行记录算出一组**可从数据直接算出**的工程指标：

- **延迟**：平均 / P50 / P95 / 最大（毫秒）
- **token 用量**：prompt / completion / 合计，以及每次运行均值
- **成功率**：完成数 / 总数
- **工具调用**：合计、每次运行均值、单次最多、有多少次运行用了工具

.. note::

   这里刻意**不做质量评估**（回答好不好、是否幻觉）—— 那需要评测集与
   裁判模型，属于后续阶段。本模块只回答「稳不稳、快不快、贵不贵」。

指标来源是 :class:`~agentos.runtime.repositories.RunRepository`：
计数与合计走 SQL 聚合，分位数需要具体数值所以单独取耗时列。
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from agentos.runtime.repositories import RunAggregate, RunRepository


class LatencyMetrics(BaseModel):
    """延迟分布，单位毫秒。"""

    avg: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    max: float = 0.0


class TokenMetrics(BaseModel):
    """token 用量。"""

    prompt: int = 0
    completion: int = 0
    total: int = 0
    avg_per_run: float = 0.0


class ToolCallMetrics(BaseModel):
    """工具调用统计。"""

    total: int = 0
    avg_per_run: float = 0.0
    max_in_run: int = 0
    runs_with_tools: int = 0


class EvaluationSummary(BaseModel):
    """一段运行记录的聚合评估结果。"""

    runs: int = 0
    succeeded: int = 0
    failed: int = 0
    success_rate: float = 0.0
    latency: LatencyMetrics = Field(default_factory=LatencyMetrics)
    tokens: TokenMetrics = Field(default_factory=TokenMetrics)
    tool_calls: ToolCallMetrics = Field(default_factory=ToolCallMetrics)
    agent: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def percentile(values: list[float], quantile: float) -> float:
    """线性插值分位数（与 numpy.percentile 的默认算法一致）。

    ``values`` 需已升序排列；空列表返回 0。
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]

    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] + (values[upper] - values[lower]) * weight


class Evaluator:
    """从运行记录计算评估指标。"""

    def __init__(self, runs: RunRepository) -> None:
        self._runs = runs

    def summarize(
        self, *, agent: str | None = None, since: datetime | None = None
    ) -> EvaluationSummary:
        """汇总指标；``agent`` 与 ``since`` 用于圈定统计范围。"""
        aggregate = self._runs.aggregate(agent=agent, since=since)
        durations = self._runs.durations(agent=agent, since=since)
        return self._build(aggregate, durations, agent=agent)

    @staticmethod
    def _build(
        aggregate: RunAggregate, durations: list[float], *, agent: str | None
    ) -> EvaluationSummary:
        return EvaluationSummary(
            runs=aggregate.runs,
            succeeded=aggregate.succeeded,
            failed=aggregate.failed,
            success_rate=round(aggregate.success_rate, 4),
            latency=LatencyMetrics(
                avg=round(aggregate.avg_duration_ms, 3),
                p50=round(percentile(durations, 0.5), 3),
                p95=round(percentile(durations, 0.95), 3),
                max=round(durations[-1], 3) if durations else 0.0,
            ),
            tokens=TokenMetrics(
                prompt=aggregate.prompt_tokens,
                completion=aggregate.completion_tokens,
                total=aggregate.total_tokens,
                avg_per_run=round(aggregate.avg_total_tokens, 2),
            ),
            tool_calls=ToolCallMetrics(
                total=aggregate.total_tool_calls,
                avg_per_run=round(aggregate.avg_tool_calls, 2),
                max_in_run=aggregate.max_tool_calls,
                runs_with_tools=aggregate.runs_with_tools,
            ),
            agent=agent,
        )
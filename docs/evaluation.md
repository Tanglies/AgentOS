# Evaluation

## 目标

Evaluation 模块把运行记录转换成可比较的工程指标，回答三个问题：

- 运行是否稳定：成功 / 失败 / success rate；
- 运行是否快：平均延迟、P50、P95、最大延迟；
- 运行是否昂贵：prompt / completion / total token，以及工具调用次数。

它**不做回答质量评分**。幻觉、准确率和人类偏好需要评测集与裁判模型，属于后续阶段。

## 目录

| 文件 | 职责 |
| --- | --- |
| `evaluation/metrics.py` | 指标模型、分位数计算、可扩展 `Metric` 抽象 |
| `evaluation/collector.py` | `Evaluator` / `EvaluationCollector`，从 `RunRepository` 聚合 |
| `evaluation/report.py` | `EvaluationReport` 的 JSON / Markdown 格式化 |
| `runtime/evaluation.py` | 兼容旧导入路径的薄转发模块 |

API 路由使用 `agentos.evaluation`，但 `GET /api/v1/evaluation/summary` 的响应字段保持
既有格式，不需要客户端迁移。

## 指标

| 指标 | 字段 |
| --- | --- |
| 延迟 | `latency.avg` / `p50` / `p95` / `max` |
| Token | `tokens.prompt` / `completion` / `total` / `avg_per_run` |
| 成功率 | `runs` / `succeeded` / `failed` / `success_rate` |
| 工具调用 | `tool_calls.total` / `avg_per_run` / `max_in_run` / `runs_with_tools` |

分位数使用线性插值，与 `numpy.percentile` 的默认算法一致；空数据集返回 0。

## 扩展 Metric

`Metric` 是扩展点：

```python
from agentos.evaluation import Metric
from agentos.runtime.repositories import RunAggregate


class CustomMetric(Metric):
    name = "custom"

    def compute(self, aggregate: RunAggregate, durations: list[float]) -> int:
        return aggregate.runs
```

`Evaluator.collect()` 会返回所有已配置指标的字典；`Evaluator.summarize()` 保持稳定的
`EvaluationSummary` API。这样新增指标不会破坏现有路由和响应模型。

## 报告

```python
from agentos.evaluation import EvaluationReport, Evaluator

summary = Evaluator(run_repository).summarize(agent="assistant")
payload = EvaluationReport.as_dict(summary)
markdown = EvaluationReport.as_markdown(summary)
```

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation.py tests/test_evaluation_package.py -q
curl.exe http://127.0.0.1:8000/api/v1/evaluation/summary?agent=assistant
```

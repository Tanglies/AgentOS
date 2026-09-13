# Evaluation Framework

## 定位

Phase 4 的 Evaluation 2.0 不再只统计系统指标，而是回答「Agent 是否按预期完成任务」。
两类评估互补：

| 类型 | 关注点 | 现有能力 |
| --- | --- | --- |
| 工程指标 | 延迟、token、成功率、工具调用量 | `GET /api/v1/evaluation/summary` |
| 质量评估 | 输出质量、工具轨迹、安全边界、回归 | `EvaluationDataset` + `Evaluator` + `EvaluationRunner` |

测试使用确定性 LLM 替身和 MockTransport，不调用真实收费模型，也不访问真实网络。

## 组件

```text
JSONL Dataset
    ↓ load_jsonl
EvaluationDataset / EvaluationCase
    ↓ EvaluationRunner（Semaphore 限制并发）
AgentRuntime.run()
    ↓ 真实 Message / ToolCall 轨迹
Evaluator 列表
    ├── ExactMatchEvaluator
    ├── ContainsEvaluator
    ├── ToolCallEvaluator / ForbiddenToolEvaluator
    ├── RuleEvaluator
    └── LLMJudgeEvaluator（可选，默认关闭）
    ↓
EvaluationResult
    ↓ EvaluationReportBuilder
Report: pass rate / average score / latency / tokens / cost / reliability
    ↓ EvaluationRegression.compare
Baseline vs Candidate 差异
```

主要代码位于：

- `src/agentos/evaluation/models.py`：数据契约
- `src/agentos/evaluation/dataset.py`：JSONL 读写与重复 ID 校验
- `src/agentos/evaluation/evaluators/`：规则与 Judge
- `src/agentos/evaluation/runner.py`：并发运行
- `src/agentos/evaluation/report.py`：质量报告
- `src/agentos/evaluation/regression.py`：回归比较
- `src/agentos/runtime/services/evaluation_service.py`：后台任务与 Workspace 隔离

## Dataset 格式

支持 JSONL，每行一个 Case。目录默认为 `evals/`。

```json
{
  "id": "calc-001",
  "name": "basic calculation",
  "input": "计算 (12+8)*3",
  "agent": "assistant",
  "expected_output": "60",
  "expected_tools": ["calculate"],
  "forbidden_tools": [],
  "tags": ["tool-calling"],
  "metadata": {}
}
```

必备字段只有 `id` 和 `input`。`expected_output`、`expected_tools`、`forbidden_tools`
为空时，对应 Evaluator 会标记为不适用，而不是误判失败。

内置 Benchmark 共 20 个 Case：

| 文件 | 覆盖 |
| --- | --- |
| `evals/tool_calling.jsonl` | 计算、时间、抓取等工具轨迹 |
| `evals/memory.jsonl` | 长期记忆写入与召回 |
| `evals/planning.jsonl` | 计划创建和步骤更新 |
| `evals/multi_agent.jsonl` | 明确委托场景 |
| `evals/safety.jsonl` | 敏感文件、危险工具、提示注入边界 |

## Evaluator

### 规则评分

- `ExactMatchEvaluator`：规范化后精确匹配期望输出。
- `ContainsEvaluator`：检查输出是否包含关键内容。
- `ToolCallEvaluator`：从 Runtime 的真实 `Message.tool_calls` 提取轨迹，校验期望工具被调用。
- `ForbiddenToolEvaluator`：禁用工具一旦执行即为失败。
- `RuleEvaluator`：支持 `contains`、`not_contains`、`equals`、`regex`、
  `max_latency_ms`、`max_tokens`、`tool_called`、`tool_not_called`。

工具评分不会依赖模型口述。即使模型声称「我已经搜索」，只要轨迹中没有
`web_search`，工具评分仍然不会通过。

### LLM Judge

`LLMJudgeEvaluator` 复用现有 `LLMClient`，只在以下条件同时满足时启用：

```powershell
$env:AGENTOS_EVALUATION__JUDGE_ENABLED = "true"
$env:AGENTOS_EVALUATION__JUDGE_MODEL = "your-judge-model"
```

Judge 返回严格 JSON；解析失败会生成不适用的评分，而不是让整个 Dataset 崩溃。
默认关闭，避免无意消耗 token 或把测试变成非确定性调用。

## API

启动评测会立即返回 `202 Accepted`，实际执行由进程内后台任务完成：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/evaluations/run `
  -H "Content-Type: application/json" `
  -d '{"dataset":"tool_calling.jsonl"}'

curl.exe http://127.0.0.1:8000/api/v1/evaluations
curl.exe http://127.0.0.1:8000/api/v1/evaluations/eval_xxxx
```

接口使用 `evaluation:run` / `evaluation:read` 权限，并按 Workspace 隔离。
Dataset 路径会解析并限制在 `AGENTOS_EVALUATION__DATASET_ROOT` 内，阻止路径穿越。

## 报告与回归

`EvaluationReportBuilder` 输出：

- `pass_rate` / `average_score`
- `average_latency` / `average_tokens`
- `tool_accuracy`
- `estimated_cost` 与 `priced_cases`（无模型价格时为 `null`）
- `reliability.timeout_rate` / `tool_error_rate` / `llm_error_rate` /
  `max_iteration_rate` / `cancelled_rate`
- `by_agent` / `by_tag` / `by_evaluator`

`EvaluationRegression.compare(baseline, candidate)` 比较两次运行的：

- `pass_rate_delta`
- `score_delta`
- `latency_delta`
- `token_delta`
- `tool_accuracy_delta`

推荐流程：

1. 固定 Dataset 和模型配置，运行 Baseline 并保存报告。
2. 修改 Prompt、工具或 Runtime。
3. 运行 Candidate，比较回归报告。
4. pass rate / score 下降时阻止合并；工程指标的下降要结合业务容忍度判断。

## 当前边界

- Dataset 是显式 JSONL，不包含自动生成器。
- Judge 是可选能力，不替代规则评分和人工审查。
- 当前执行器是进程内 `asyncio.create_task`，没有独立 worker 队列；服务重启时
  进行中的 Evaluation 会中断。
- 向量数据库、RAG 和前端评测页面不在 Phase 4 范围内。
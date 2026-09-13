# Telemetry

## 目标

Phase 4 的可观测性分为三层：

1. **Trace**：一次请求内部的调用树和耗时。
2. **Metrics**：低基数、可聚合的时间序列。
3. **Audit / Logs**：谁在何时对什么做了什么，以及排障上下文。

实现位于 `src/agentos/observability/`，默认全部关闭，不报告时接近零开销。

## OpenTelemetry Tracing

开启配置：

```powershell
$env:AGENTOS_OBSERVABILITY__ENABLED = "true"
$env:AGENTOS_OBSERVABILITY__SERVICE_NAME = "agentos"
$env:AGENTOS_OBSERVABILITY__OTLP_ENDPOINT = "http://127.0.0.1:4318"
$env:AGENTOS_OBSERVABILITY__EXPORT_TRACES = "true"
$env:AGENTOS_OBSERVABILITY__SAMPLE_RATIO = "1.0"
```

Span 结构：

```text
http.request
└── agent.run
    ├── repository.query
    ├── llm.call
    ├── tool.call
    │   └── repository.query
    └── llm.call
```

已覆盖的 Span：

| Span | 内容 |
| --- | --- |
| `http.request` | method、path、status、request_id、trace_id |
| `agent.run` | agent、iterations、tool call count、duration、memory budget |
| `llm.call` | model、status、延迟、token 统计 |
| `tool.call` | tool、call id、成功/失败、timeout |
| `repository.query` | SQLite Repository 操作 |

上下文会把 `trace_id` 和 `span_id` 写入运行结果和审计记录，便于从 HTTP 请求
跳到具体 Agent Run，再到具体工具调用。

### 敏感字段过滤

Trace 属性过滤器会过滤属性名中含以下内容的字段：

- `prompt`
- `content`
- `api_key`
- `authorization`
- `password`
- `secret`
- `token`
- `memory`

Prompt、API Key、消息正文和长期记忆内容不会写入 Span 属性。审计日志仍按
配置的 `redact_keys` 脱敏。

## Prometheus Metrics

开启配置：

```powershell
$env:AGENTOS_OBSERVABILITY__PROMETHEUS_ENABLED = "true"
$env:AGENTOS_OBSERVABILITY__METRICS_PATH = "/metrics"
```

```powershell
curl.exe http://127.0.0.1:8000/metrics
```

指标清单：

| 指标 | 标签 | 说明 |
| --- | --- | --- |
| `agentos_runs_total` | `agent`, `status` | 运行次数，status 可为 completed / failed / cancelled |
| `agentos_run_duration_seconds` | `agent` | 运行耗时 histogram |
| `agentos_run_errors_total` | `agent`, `error_type` | 运行错误次数 |
| `agentos_llm_requests_total` | `model`, `status` | LLM 调用次数 |
| `agentos_llm_duration_seconds` | `model` | LLM 调用耗时 |
| `agentos_llm_tokens_total` | `model`, `type` | prompt / completion token |
| `agentos_tool_calls_total` | `tool`, `status` | 工具调用次数 |
| `agentos_tool_duration_seconds` | `tool` | 工具执行耗时 |
| `agentos_tool_timeouts_total` | `tool` | 工具超时次数 |

不会把 `run_id`、`workspace_id`、`user_id`、Prompt 或 URL 当作 label，
避免高基数指标把 Prometheus 内存打满。

## Reliability 指标

Dashboard 提供 `/api/v1/dashboard/reliability`，直接复用 Run History 的聚合：

| 指标 | 分母 |
| --- | --- |
| `timeout_rate` | tool call 总数 |
| `tool_error_rate` | tool call 总数 |
| `llm_error_rate` | LLM call 总数 |
| `max_iteration_rate` | 运行总数 |
| `cancelled_rate` | 运行总数 |

Evaluation Report 也会计算同一组指标，因此 Dashboard、回归报告和线上告警使用
同一套定义。

## 采样与开销

- `enabled=false` 时所有 span 都是 no-op。
- `prometheus_enabled=false` 时 metrics 不创建，`/metrics` 返回 404。
- OpenTelemetry 使用进程内 SDK；导出到 OTLP 需要外部 collector 或兼容接收端。
- 采样比例建议：本地 1.0，生产按流量降低；错误是否全量采样由 collector 配置决定。

## 当前边界

- 没有内置 Grafana dashboard JSON。
- OTel 仅覆盖 AgentOS 进程内 Span；LLM 提供方内部和外部数据库不在当前 trace 中。
- SQLite 不提供分布式事务语义；Repository span 主要用于耗时定位。
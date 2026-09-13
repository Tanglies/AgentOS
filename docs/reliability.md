# Reliability / Performance

## 目标

可靠性优化不改变 Agent 的语义，只处理四类问题：取消、超时、并发竞争、资源无界增长。
所有开关默认值都优先选择安全路径，生产环境再显式提高吞吐。

## Cancellation

SSE 客户端断开时，FastAPI 会取消响应生成器；取消信号会向 Runtime 和上游
LLM stream 传播：

```text
client disconnect
  → ASGI cancellation
  → AgentRuntime.run_stream
  → LLM stream / Tool execution
  → stop remaining work
```

Runtime 捕获 `asyncio.CancelledError` 后：

1. 停止后续工具；
2. 写入 `cancelled` Run History；
3. 记录审计和 Prometheus cancelled 指标；
4. 继续抛出取消，让 ASGI 正确结束连接。

测试位于 `tests/test_cancellation.py`，使用可控 LLM 流验证不会在客户端离开后继续消费。

## Streaming Backpressure

流式响应直接使用 FastAPI `StreamingResponse` 的异步迭代协议，不先把所有 chunk
收集到内存。消费速度由客户端和 ASGI 服务器自然施加背压；实现没有无界 SSE 队列。

`llm.call` 只累计 token 与耗时，不缓存正文。运行结束后需要的历史消息写入
Run History，而不是保留无限的增长队列。

## Tool Timeout

`ToolRegistry` 在统一执行点应用超时：

- `Tool.timeout_seconds` 优先；
- 未设置时使用 `AGENTOS_TOOLS__DEFAULT_TIMEOUT_SECONDS`；
- `run_command` 仍有自己的 shell timeout；
- 超时返回 `ToolCallResult(is_error=True, error_type="timeout")`，回填给模型，
  不抛出到 Runtime。

`agentos_tool_timeouts_total` 和 `/dashboard/reliability` 的 `timeout_rate` 可用于
发现循环依赖、慢网络或失控本地工具。

## Parallel-safe Tools

工具默认 `parallel_safe=False`。只有明确无副作用的工具才开启：

- `calculate`
- `get_current_time`
- `list_directory`
- `read_file`
- `search_text`
- `fetch_url`
- `web_search`
- `recall`

`write_file`、`run_command`、`remember`、`create_plan`、`update_plan_step`、
`delegate_to_agent` 保持顺序执行。Runtime 把连续 parallel-safe 调用组成一个批次，
批次之间严格保序；有副作用的工具不会被简单 `gather`。

## Web Cache

`fetch_url` 可启用进程内 TTL + LRU cache：

```text
AGENTOS_TOOLS__WEB_CACHE_ENABLED=true
AGENTOS_TOOLS__WEB_CACHE_TTL_SECONDS=300
AGENTOS_TOOLS__WEB_CACHE_MAX_ENTRIES=128
```

规则：

- 只有 `text/html`、`text/plain`、`application/xhtml+xml` 等稳定文本响应可缓存；
- `cache-control: no-store/private` 与 `set-cookie` 响应不缓存；
- URL 含 token、api_key、password、signature 等敏感查询参数时不缓存；
- 错误响应不缓存；
- 缓存有最大条数和 TTL，不会无限增长。

当前是单进程缓存，部署多副本时每个副本独立失效；后续可替换为 Redis。

## Memory Context Budget

长期记忆每次注入受三重限制：

- `AGENTOS_MEMORY__LONG_TERM_RECALL_LIMIT`
- `AGENTOS_MEMORY__LONG_TERM_MAX_CONTEXT_CHARS`
- `AGENTOS_MEMORY__LONG_TERM_MAX_CONTEXT_TOKENS`

预算按字符和近似 token 双重检查，超出时截断最后一条记忆，不拆散已有格式。
运行结果记录 `memory_recall_count` 与 `memory_context_chars`，可在 Run History、
日志和 OTel 属性中观察。

token 数是保守估算（CJK 每字约一个 token，ASCII 约四字符一个 token），
不会替代具体 provider 的 tokenizer。

## Cost Tracking

价格完全由配置提供，不硬编码任何厂商价格：

```powershell
$env:AGENTOS_LLM__PRICING = '{"your-model":{"prompt_tokens_per_million":0.5,"completion_tokens_per_million":1.5}}'
```

Runtime 根据实际累计 `TokenUsage` 计算 `estimated_cost`。没有配置价格的模型返回
`null`，不会伪装成 0；单位由部署方自行约定（通常为供应商账单货币）。

Run History、Evaluation Report 和 API 响应都携带 `estimated_cost`。Dashboard/费用
告警可使用 RunRepository 的聚合结果。

## Reliability Metrics

`RunAggregate.reliability` 是 Dashboard 与 Evaluation 共用的计算：

| 指标 | 公式 |
| --- | --- |
| `timeout_rate` | tool timeouts / tool calls |
| `tool_error_rate` | tool errors / tool calls |
| `llm_error_rate` | LLM errors / LLM calls |
| `max_iteration_rate` | max-iteration runs / runs |
| `cancelled_rate` | cancelled runs / runs |

没有分母时返回 0。运行失败也会写入计数，因此失败率不会被成功路径「洗掉」。

## 失败处理原则

- 单次 Tool 失败返回给模型，不直接把整次 Agent 运行判死；
- LLM 错误进入 Run History 的 failed 记录并触发 `llm_error_count`；
- max iterations 标记 `max_iterations_reached`，保留最后一次可诊断状态；
- 客户端取消保留 cancelled 状态，不写 completed；
- cache 和 memory budget 都必须在配置边界内，不能靠进程重启清空来解决容量问题。
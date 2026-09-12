# Quotas and Rate Limits

## Workspace Quota

`workspace_quotas` 支持：

| 字段 | 说明 |
| --- | --- |
| `daily_run_limit` | 每日 Run 上限 |
| `daily_token_limit` | 每日 Token 上限 |
| `requests_per_minute` | 每分钟请求上限 |
| `max_iterations_per_run` | 单次 Run 最大迭代 |
| `max_tool_calls_per_run` | 单次 Run 最大工具调用数 |

未配置时使用 `AGENTOS_QUOTA__*` 默认值。默认：

```text
daily_run_limit = 1000
daily_token_limit = 1000000
requests_per_minute = 60
max_iterations_per_run = 8
max_tool_calls_per_run = 10
```

## API

```text
GET   /api/v1/quota
PATCH /api/v1/quota
GET   /api/v1/usage?period=day|month
GET   /api/v1/dashboard/usage
```

`/quota` 只能操作当前认证身份的 Workspace。修改需要 `quota:write`。

## Run 执行检查

每次 Run 前：

1. 聚合当天当前 Workspace 的 Run 数；
2. 聚合当天当前 Workspace 的 Token；
3. 超过配额返回 `429 quota_exceeded`；
4. 将 `max_iterations_per_run` 和 `max_tool_calls_per_run` 传给 Runtime。

Run 记录始终带 `workspace_id` 和 `user_id`。

## Rate Limiter

`RateLimiter` 是抽象接口，第一版实现：

```text
InMemorySlidingWindowRateLimiter
```

限制键：

```text
workspace_id + actor/API key
```

超出请求数返回：

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "workspace request rate exceeded"
  }
}
```

限流发生后写入 `rate_limit.exceeded` 审计事件。该实现是单进程的，
多实例部署应替换为 Redis 等共享 limiter。

## Usage

`GET /api/v1/usage` 从 Run History 聚合：

- Runs；
- prompt / completion / total tokens；
- tool calls；
- 当前 period。

不创建重复统计数据。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_quota.py tests/test_rate_limit.py tests/test_usage.py -q
```

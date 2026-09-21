# Agent Platform 能力

## 定位

AgentOS 已从可运行的单体 Agent Framework 扩展为 Agent Platform MVP。
平台层关注 Agent 的创建、配置、持久化、运行追踪和指标查询；Runtime
仍只负责一次运行的模型调用、工具执行和结果产出。

平台层包含：

- Agent 生命周期管理；
- 结构化 Agent 持久化；
- Run History 查询；
- Dashboard 只读数据接口；
- Evaluation 基础指标；
- API Key 权限与审计追溯。

## 分层边界

```text
api routes / schema
        ↓
runtime services       AgentService / DashboardService
        ↓
repositories            AgentRepository / RunRepository / ToolRepository
        ↓
database                DatabaseManager / migration / SQLite
```

约束：

- API 不直接执行 SQL；
- Service 负责业务编排和审计，不处理 HTTP 细节；
- Repository 负责 SQL 与持久化模型转换；
- Runtime 仍负责 Agent 执行，不反向依赖 API；
- Dashboard 只读复用现有数据，不复制统计源。

## Agent 生命周期

### 创建

```http
POST /api/v1/agents
```

请求字段：

```json
{
  "name": "researcher",
  "description": "搜索与归纳",
  "system_prompt": "只返回可靠结论",
  "model": "qwen3.8-max",
  "temperature": 0.2,
  "max_iterations": 5,
  "tools": ["read_file"],
  "metadata": {"team": "data"}
}
```

`name` 必须匹配 Agent 名称规则；重复名称返回 `409 conflict`。
创建成功后返回 `id`、完整配置、`created_at` 和 `updated_at`。

### 查询列表

```http
GET /api/v1/agents?page=1&page_size=20
```

响应保留 `items` / `total`，并增加：

- `page`：当前页码；
- `page_size`：每页数量。

默认按名称稳定排序。

### 查询详情

```http
GET /api/v1/agents/{name}
```

返回完整 `AgentSummary`，包括提示词、模型参数、工具、metadata 和时间戳。

### 删除

```http
DELETE /api/v1/agents/{name}
```

不存在时返回 `404 not_found`；删除后再次查询返回 404。
底层 `AgentRegistry.unregister()` 继续保留，`delete()` 是其语义别名。

## 数据模型

`agents` 表使用结构化列：

| 字段 | 含义 |
| --- | --- |
| `id` | 数据库自增标识 |
| `name` | Agent 唯一名称 |
| `description` | 描述 |
| `system_prompt` | 系统提示词 |
| `model` | Agent 默认模型 |
| `temperature` | 默认采样温度 |
| `max_iterations` | 最大迭代轮数 |
| `tools` | 工具名 JSON 数组 |
| `metadata` | 扩展元数据 JSON |
| `payload` | 旧版本完整 Agent JSON 兼容字段 |
| `created_at` | 创建时间 |
| `updated_at` | 最后更新时间 |

旧数据库没有结构化列时，`AgentRepository` 会在初始化时检查
`PRAGMA table_info(agents)`，只补缺失列，并从旧 `payload` 回填能识别到的字段。
因此旧 Agent 不需要手工迁移即可继续读取。

## Run History

```http
GET /api/v1/runs
```

支持的查询参数：

| 参数 | 说明 |
| --- | --- |
| `agent` | 按 Agent 过滤 |
| `status` | `completed` / `failed` |
| `page` / `page_size` | 页码分页 |
| `limit` / `offset` | 旧分页参数，继续兼容 |
| `cursor` | 上一页返回的 `next_cursor`，用于并发写入下稳定的 keyset 分页 |
| `sort` | `created_at` / `-created_at` |
| `order` | `asc` / `desc` |

`RunSummary` 保留原有字段，并新增：

```json
{
  "token_usage": {
    "prompt_tokens": 8,
    "completion_tokens": 2,
    "total_tokens": 10
  }
}
```

原 `total_tokens` 字段继续返回，避免破坏旧客户端。

首次请求可以继续使用 `page/page_size` 或 `limit/offset`；当响应中的
`next_cursor` 非空时，将它原样传给下一页即可。cursor 不可与 `page`、
`page_size` 或非零 `offset` 混用，翻页期间也必须保持相同的过滤条件和
`order`。

```http
GET /api/v1/runs?limit=20&cursor=eyJjcmVhdGVkX2F0IjoiLi4uIn0
```

## Dashboard 数据来源

### Overview

```http
GET /api/v1/dashboard/overview
```

返回：

```json
{
  "total_runs": 12,
  "success_rate": 0.9167,
  "average_latency": 1832.5,
  "total_tokens": 11523,
  "active_agents": 3
}
```

数据来源：

- `runs`：运行数、成功率、平均延迟、token；
- `AgentRegistry`：活跃 Agent 数。

### Tools

```http
GET /api/v1/dashboard/tools
```

返回按工具名聚合的调用次数：

```json
{
  "calculate": 120,
  "search_text": 80
}
```

数据来源是审计日志中的 `tool.execute` 事件，不维护第二张工具统计表。
`ToolRepository` 负责按 `target` / `tool_name` 聚合。

### Errors

```http
GET /api/v1/dashboard/errors
```

返回最近的失败运行摘要：

```json
[
  {
    "run_id": "run_...",
    "agent": "assistant",
    "status": "failed",
    "error": "max_iterations exceeded",
    "duration_ms": 120.5,
    "created_at": "2026-09-12T08:00:00Z"
  }
]
```

数据来源是 `runs` 表中 `status=failed` 的记录，按时间倒序。

## Evaluation

`GET /api/v1/evaluation/summary` 保留原有嵌套指标，并增加顶层平均值：

- `average_latency`；
- `average_tokens`；
- `average_tool_calls`。

这样 Dashboard 和简单客户端不需要进入嵌套结构即可读取常用均值。

## 权限

新增 `dashboard:read` 权限。默认数据库密钥包含该权限；更细的角色可由 API Key
签发时的权限列表控制。Agent 和 Run 接口继续使用原有：

- `agent:read` / `agent:write`；
- `run:read` / `run:create`；
- `evaluation:read`。

认证关闭时保持本地开发放行；认证开启时缺少权限返回 403。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_repository.py tests/test_agent_api.py tests/test_run_query_api.py tests/test_dashboard_api.py tests/test_evaluation_api.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

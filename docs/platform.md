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
- `page_size`：每页数量；
- `next_cursor`：下一页的不透明 keyset 游标，`null` 表示已到末页。

默认按名称稳定排序。翻页有两种等价方式：

1. **页码分页**：继续使用 `page` / `page_size`，行为与旧版本一致；
2. **keyset 分页**：把上一页响应的 `next_cursor` 原样传回，可同时指定
   `page_size` 控制每页数量；翻页期间有 Agent 被创建或删除也不会重复或跳过记录。

```http
GET /api/v1/agents?page_size=20&cursor=eyJ2IjoyLCJrZXkiOiJhbHBoYSJ9
```

`cursor` 不能与 `page` 同时使用，也不能跨列表或跨接口复用：Agent 列表的游标
记录的是名称位置，Run History 的游标记录的是创建时间，混用会返回
`422 validation_error`。

### 查询详情

```http
GET /api/v1/agents/{name}
```

返回完整 `AgentSummary`，包括提示词、模型参数、工具、metadata 和时间戳。

### 更新

单条更新使用部分更新语义，只修改请求中明确出现的字段：

```http
PATCH /api/v1/agents/{name}
```

```json
{
  "description": "更新后的职责",
  "model": "qwen3.8-flash",
  "temperature": 0.3
}
```

未出现字段保持原值。需要清空字段时显式传 `null`：

- `system_prompt`、`model`、`temperature`、`max_iterations` 清为 `null`；
- `description` 清为空字符串；
- `tools`、`metadata` 清为空数组 / 空对象。

请求至少包含一个可更新字段，否则返回 `422 validation_error`。Agent 不存在
或不属于当前 Workspace 时返回 `404 not_found`。

### 批量更新

```http
PATCH /api/v1/agents/batch
```

```json
{
  "updates": [
    {"name": "researcher", "description": "调研主管"},
    {"name": "summarizer", "tools": ["calculate"], "temperature": 0.2}
  ]
}
```

单次最多 100 条；空列表、重复名称、空补丁、非法名称以及字段越界返回
`422 validation_error`。响应按请求顺序返回实际更新的 Agent：

```json
{
  "requested": 3,
  "updated": 2,
  "items": [
    {"name": "researcher", "description": "调研主管", "...": "..."},
    {"name": "summarizer", "temperature": 0.2, "...": "..."}
  ],
  "missing_names": ["deleted-worker"]
}
```

SQLite 后端在单个事务内读取当前 Workspace 可见记录并应用所有补丁；任一条
合并后的 Agent 校验失败会回滚整个批次。不存在或无权访问的名称只进入
`missing_names`，不暴露其他 Workspace 的状态。每个实际更新会记录
`agent.update` 审计事件。

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

## Agent 批量删除

```http
POST /api/v1/agents/batch-delete
```

请求体：

```json
{
  "names": ["researcher", "summarizer", "obsolete-worker"]
}
```

单次最多 100 条；空列表、重复名称、空名称、不符合
`^[A-Za-z0-9_-]+$` 的名称和超长名称返回 `422 validation_error`。
删除只作用于当前 Workspace 可见的 Agent；不存在或无权访问的名称统一计入
`missing_names`，不暴露其他 Workspace 的状态。

```json
{
  "requested": 3,
  "deleted": 2,
  "missing_names": ["obsolete-worker"]
}
```

SQLite 后端的可见性确认与删除在单个事务内执行，并为每个实际删除的 Agent
记录 `agent.unregister` 审计事件。单条 `DELETE /api/v1/agents/{name}`
保持兼容。

## 长期 Memory 批量删除

```http
POST /api/v1/memories/batch-delete
```

请求体：

```json
{
  "ids": [12, 18, 24]
}
```

单次最多 100 条，重复 ID、非正整数和空列表返回 `422 validation_error`。
删除只作用于当前 Workspace 可见的记忆；USER scope 记录还必须属于当前
用户。不存在或无权访问的 ID 统一计入 `missing_ids`，不暴露其他租户状态。

```json
{
  "requested": 3,
  "deleted": 2,
  "missing_ids": [24]
}
```

实现会在单个 SQLite 事务内先确认可见 ID 再执行删除，避免部分失败时
返回不准确的删除结果。单条 `DELETE /api/v1/memories/{memory_id}` 保持兼容。

## API Key 列表

```http
GET /api/v1/api-keys?limit=50
```

支持的查询参数：

| 参数 | 说明 |
| --- | --- |
| `include_revoked` | 是否包含已吊销（软删除）的记录，默认 `false` |
| `limit` | 每页数量，默认 50，最大 500 |
| `cursor` | 上一页返回的 `next_cursor`，用于并发写入下稳定的 keyset 分页 |

响应保留 `items` / `total`，并新增 `next_cursor`；`total` 是过滤后的**总数**，
不是本页条数，`next_cursor` 为 `null` 表示已到末页。

列表按数据库自增 `id` 升序返回，游标记录的是上一页最后一条记录的 id：

```http
GET /api/v1/api-keys?limit=50&cursor=eyJ2IjoyLCJrZXkiOiI3In0
```

因此翻页期间**签发新密钥**只会追加在游标之后，**吊销密钥**也不会让后续页面
跳过记录（除非显式使用 `include_revoked=true`）。Agent 名称游标、Run History
时间游标等跨列表游标都会被拒绝为 `422 validation_error`。

## API Key 批量吊销

```http
POST /api/v1/api-keys/batch-revoke
```

请求体：

```json
{
  "ids": [12, 18, 24]
}
```

单次最多 100 条，重复 ID、非正整数和空列表返回 `422 validation_error`。
吊销只作用于当前 Workspace 中仍有效的密钥；不存在、已吊销或无权访问的 ID
统一计入 `missing_ids`，不暴露其他 Workspace 的状态。

```json
{
  "requested": 3,
  "revoked": 2,
  "missing_ids": [24]
}
```

确认与吊销在单个 SQLite 事务内执行，并继续使用软删除保留审计线索。单条
`DELETE /api/v1/api-keys/{key_id}` 保持兼容。

## Audit 列表

```http
GET /api/v1/audit?limit=50
```

Audit 保留原有的 JSON 数组响应，避免破坏已有客户端；当还有下一页时，
响应头 `X-Next-Cursor` 携带不透明游标：

```http
GET /api/v1/audit?limit=50&cursor=eyJjcmVhdGVkX2F0IjoiLi4uIn0
```

游标以 `created_at + id` 定位，翻页期间新增或删除此前未读记录也不会让当前
游标位置漂移。支持的参数包括 `action` / `actor` / `run_id` / `status` /
`order` / `limit` / `offset` / `cursor`；旧 `offset` 分页保持可用，
但 `cursor` 不能与非零 `offset` 同时使用。游标方向必须与 `order` 一致，
跨列表游标或损坏游标返回 `422 validation_error`。

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

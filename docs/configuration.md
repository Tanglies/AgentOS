# 配置说明

## 加载优先级

从高到低：

1. **环境变量**：前缀 `AGENTOS_`，嵌套字段用 `__` 分隔
2. **`.env` 文件**：项目根目录，参考 `.env.example`
3. **代码默认值**：见 `src/agentos/core/config.py`

示例：设置 LLM 提供方与模型

```powershell
$env:AGENTOS_LLM__PROVIDER = "openai_compatible"
$env:AGENTOS_LLM__MODEL = "deepseek-chat"
```

复杂类型（列表、字典）在环境变量中需使用 JSON，例如：

```powershell
$env:AGENTOS_API__CORS_ORIGINS = '["https://app.example.com"]'
```

配置对象默认缓存（`get_settings()` 使用 `lru_cache`），测试中可调用 `reset_settings_cache()` 清空。

## 配置项

### 应用级

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_APP_NAME` | `AgentOS` | 应用名，出现在日志与 OpenAPI 标题 |
| `AGENTOS_ENVIRONMENT` | `local` | `local` / `dev` / `staging` / `production` |
| `AGENTOS_DEBUG` | `false` | 调试开关 |

### LLM（`llm`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_LLM__PROVIDER` | `echo` | `echo` / `openai_compatible` / `openai`（后两者等价） |
| `AGENTOS_LLM__MODEL` | `gpt-4o-mini` | 模型名，`echo` 提供方忽略此值 |
| `AGENTOS_LLM__BASE_URL` | `https://api.openai.com/v1` | 服务地址，需兼容 `/chat/completions` |
| `AGENTOS_LLM__API_KEY` | 空 | API Key，日志与序列化中自动脱敏 |
| `AGENTOS_LLM__TIMEOUT_SECONDS` | `60` | 单次请求超时（秒） |
| `AGENTOS_LLM__MAX_RETRIES` | `2` | 可重试错误的最大重试次数（0-10） |
| `AGENTOS_LLM__TEMPERATURE` | `0.0` | 默认采样温度（0.0-2.0） |
| `AGENTOS_LLM__MAX_TOKENS` | 空 | 默认最大输出 token |
| `AGENTOS_LLM__PRICING` | `{}` | 可选模型价格 map，用于估算 cost；格式见下方示例 |

可重试状态码：`408 409 425 429 500 502 503 504`；重试使用指数退避。
超时映射为 `LLMTimeoutError`（HTTP 504），上游 4xx/5xx 映射为 `LLMProviderError`（HTTP 502）。

### Runtime（`runtime`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_RUNTIME__DEFAULT_AGENT` | `assistant` | 默认 Agent 名称，`POST /api/v1/runs` 未指定时使用 |
| `AGENTOS_RUNTIME__MAX_ITERATIONS` | `8` | 单次运行的最大迭代轮数（1-64），超出抛 `AgentRuntimeError` |
| `AGENTOS_RUNTIME__SYSTEM_PROMPT` | `You are AgentOS, a helpful AI agent.` | 默认助手的系统提示词 |

### 审计日志（`audit`）

记录「谁、什么时候、对什么做了什么、结果如何」。与运行记录分开存：
运行记录面向排查（量大），审计面向追责（量小、字段固定、需长期保留）。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_AUDIT__ENABLED` | `true` | 是否记录审计 |
| `AGENTOS_AUDIT__DB_PATH` | `.agentos/audit.db` | SQLite 文件路径 |
| `AGENTOS_AUDIT__MAX_RECORDS` | `20000` | 保留最近 N 条（1-100万） |

记录的动作：`agent.run` / `tool.execute` / `agent.register` / `agent.unregister`。
所有上下文（actor / trace_id / run_id / agent_name / tool_name）**自动从
contextvars 读取**，调用方只需说明做了什么。详见 [可观测性](observability.md)。

### 运行记录（`runs`）

记录每次 Agent 运行的输入、输出、token 用量与消息轨迹，支持历史查询。
**默认开启** —— 运行历史是排查问题的主要依据，不落盘就没有意义。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_RUNS__ENABLED` | `true` | 是否记录运行历史 |
| `AGENTOS_RUNS__DB_PATH` | `.agentos/runs.db` | SQLite 文件路径（已 gitignore） |
| `AGENTOS_RUNS__MAX_RECORDS` | `10000` | 保留最近 N 条，超出淘汰最旧的（1-100万） |

成功与**失败**都会记录：失败的运行同样需要留痕，否则排查时只能翻日志。

### Agent 注册表（`registry`）

默认使用**内存**注册表，进程重启后 Agent 定义会丢失。
开启持久化后落盘到 SQLite，重启不再丢。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_REGISTRY__PERSIST` | `false` | 是否把 Agent 定义持久化到 SQLite |
| `AGENTOS_REGISTRY__DB_PATH` | `.agentos/agents.db` | SQLite 文件路径 |

存储方式是把 `Agent` 序列化成 JSON 存进 `payload` 列，而不是为每个字段建列 ——
Agent 定义仍在演进（工具、记忆、规划都会往上挂），JSON 列免去每次加字段都改表。

启动时如果默认 Agent 不存在会**补种一个**；已存在的不会被覆盖，
所以你自定义过的默认助手不会被重启冲掉。

### 认证与权限（`auth` + `api_keys`）

API Key 认证**默认关闭**以方便本地开发；对外暴露前必须开启。认证来源有两种：

1. `AGENTOS_AUTH__API_KEYS` 配置的静态密钥：视为管理员（`*`），用于引导签发；
2. `api_keys` 表中的数据库密钥：带名称、权限、创建时间、最后使用时间与吊销时间。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_AUTH__ENABLED` | `false` | 是否开启认证 |
| `AGENTOS_AUTH__API_KEYS` | `[]` | 静态引导密钥列表（JSON 数组） |
| `AGENTOS_AUTH__HEADER_NAME` | `X-API-Key` | 承载密钥的请求头名 |
| `AGENTOS_AUTH__PUBLIC_PATHS` | `["/health","/health/ready","/docs","/redoc","/openapi.json"]` | 免认证路径 |
| `AGENTOS_API_KEYS__ENABLED` | `true` | 是否启用数据库密钥存储与管理接口 |
| `AGENTOS_API_KEYS__DB_PATH` | `.agentos/api_keys.db` | 密钥数据库文件路径 |

权限采用 `资源:动作` 命名，包含 `agent:read` / `agent:write` / `run:create` /
`run:read` / `tool:read` / `tool:execute` / `session:read` / `session:write` /
`memory:read` / `memory:write` / `evaluation:read` / `dashboard:read` /
`audit:read` / `user:read` / `user:write` / `workspace:read` / `workspace:write` /
`quota:read` / `quota:write` / `usage:read` / `tool:admin` /
`apikey:admin`；`*` 表示全部权限。路由级依赖负责授权，工具执行点还会再次
检查 `tool:execute`，确保模型无法绕过路由权限直接调用工具。

数据库只保存 SHA-256 哈希，明文只在 `POST /api/v1/api-keys` 响应中出现一次；
列表接口不返回明文或哈希。吊销是软删除，认证会立即失效但保留审计记录。
开启认证且没有任何可用密钥时，服务**拒绝所有请求**（fail closed）。

```powershell
$env:AGENTOS_AUTH__ENABLED = "true"
$env:AGENTOS_AUTH__API_KEYS = '["sk-bootstrap-admin"]'
# 用静态管理员签发普通密钥
$body = '{"name":"worker","permissions":["run:read","tool:read","tool:execute"]}'
curl.exe http://127.0.0.1:8000/api/v1/api-keys `
  -H "X-API-Key: sk-bootstrap-admin" `
  -H "Content-Type: application/json" `
  -d $body
```

当前认证是平台级 API Key；User / Workspace 模型、资源隔离、Quota 与 Rate Limit 已在 Phase 3 完成。
面向终端用户的 username/password + JWT/session 登录体系尚未实现，见 TODO。

### 记忆（`memory`）

会话记忆当前是**进程内短期记忆**，且**默认开启**：不传 `session_id` 时落到
`default_session_id` 指定的默认会话，进程重启清空。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_MEMORY__DEFAULT_SESSION_ID` | `default` | 未传 `session_id` 时使用的会话；设为空字符串则恢复无状态 |
| `AGENTOS_MEMORY__MAX_MESSAGES_PER_SESSION` | `50` | 单会话保留的最大消息条数（1-1000） |
| `AGENTOS_MEMORY__MAX_SESSIONS` | `1000` | 进程内会话数上限，超出按 LRU 淘汰 |

**优先级**：显式 `session_id` > 显式 `history`（调用方自行管理，不读写记忆）> 默认会话。

截断按**完整轮次**对齐：只保留从一个 `user` 消息开始的片段，
避免把 `assistant(tool_calls)` 与其后的 `tool` 结果拆散 —— 那样再发给
OpenAI 兼容接口会因为 tool_calls 缺少对应结果而报错。

**长期记忆**跨会话保留，落盘到 SQLite：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_MEMORY__LONG_TERM_ENABLED` | `true` | 是否启用长期记忆（含 `remember` / `recall` 工具） |
| `AGENTOS_MEMORY__LONG_TERM_DB_PATH` | `.agentos/memory.db` | SQLite 文件路径，已加入 `.gitignore` |
| `AGENTOS_MEMORY__LONG_TERM_AUTO_RECALL` | `true` | 每次运行前是否自动召回并注入系统提示词 |
| `AGENTOS_MEMORY__LONG_TERM_RECALL_LIMIT` | `5` | 单次最多召回条数（1-20） |
| `AGENTOS_MEMORY__LONG_TERM_MAX_CONTEXT_CHARS` | `6000` | 注入系统提示词的长期记忆字符预算（64-100000） |
| `AGENTOS_MEMORY__LONG_TERM_MAX_CONTEXT_TOKENS` | `1500` | 注入系统提示词的近似 token 预算（16-100000） |

检索是**关键词匹配**：查询切成英文词与中文二元组，按命中词长度加权排序。
这样不需要 embedding 依赖、也不额外调用模型；代价是同义改写召回率有限，后续可换成向量检索。

### 工具（`tools`）

本地工具让 Agent 具备读写工作区、搜索文本与执行命令的能力。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_TOOLS__WORKSPACE_ROOT` | `.` | 文件工具的沙箱根目录，越界路径一律拒绝 |
| `AGENTOS_TOOLS__ALLOW_FILE_WRITE` | `true` | 是否启用 `write_file`；覆盖已有文件仍需传 `overwrite=true` |
| `AGENTOS_TOOLS__ALLOW_SHELL` | `false` | 是否启用 `run_command`（**危险，默认关闭**） |
| `AGENTOS_TOOLS__SHELL_TIMEOUT_SECONDS` | `30` | 命令执行超时（1-600 秒） |
| `AGENTOS_TOOLS__MAX_READ_BYTES` | `256000` | 单文件读取上限（字节） |
| `AGENTOS_TOOLS__MAX_OUTPUT_CHARS` | `16000` | 工具输出回填给模型的最大字符数 |
| `AGENTOS_TOOLS__DEFAULT_TIMEOUT_SECONDS` | `30` | ToolRegistry 统一执行超时；Tool 可单独覆盖 |

#### 联网工具

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_TOOLS__WEB_TIMEOUT_SECONDS` | `15` | 网页抓取与搜索的请求超时（1-120 秒） |
| `AGENTOS_TOOLS__MAX_WEB_BYTES` | `512000` | 单次抓取的响应体上限（字节） |
| `AGENTOS_TOOLS__WEB_CACHE_ENABLED` | `true` | `fetch_url` 进程内 TTL cache 开关 |
| `AGENTOS_TOOLS__WEB_CACHE_TTL_SECONDS` | `300` | cache TTL（秒） |
| `AGENTOS_TOOLS__WEB_CACHE_MAX_ENTRIES` | `128` | cache 最大条目数，超出按 LRU 淘汰 |
| `AGENTOS_TOOLS__WEB_SEARCH_API_URL` | `https://api.tavily.com/search` | 搜索接口地址（Tavily 兼容） |
| `AGENTOS_TOOLS__WEB_SEARCH_API_KEY` | 空 | 搜索 API Key；**未配置时不注册 `web_search`** |
| `AGENTOS_TOOLS__WEB_SEARCH_MAX_RESULTS` | `5` | 单次搜索返回的最大结果数（1-20） |

`fetch_url` 的 SSRF 防护：只允许 `http`/`https`，且目标必须解析到**公网地址** ——
回环、内网、链路本地与保留地址（含云元数据 `169.254.169.254`）全部拒绝；
重定向逐跳重新校验，避免「先公网再 302 到内网」绕过。

**安全模型**

- 文件工具的路径统一经过 `WorkspaceSandbox` 解析：`..` 逃逸、外部绝对路径、
  指向外部的符号链接都会被拒绝
- 敏感文件黑名单：`.env` 与 `.env.*`（`.env.example` 除外）、`*.key` / `*.pem` / `*.p12`、
  `id_rsa` 等私钥、`*apikey*.csv`，以及 `secrets/`、`.ssh/`、`.aws/`、`.gnupg/`、`.kube/` 目录
- `run_command` 执行的是真实 shell，**命令内部不受沙箱约束**，请只在受信任环境开启

### API（`api`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_API__HOST` | `127.0.0.1` | 监听地址 |
| `AGENTOS_API__PORT` | `8000` | 监听端口 |
| `AGENTOS_API__ROOT_PATH` | 空 | 反向代理子路径 |
| `AGENTOS_API__ENABLE_DOCS` | `true` | 是否暴露 `/docs`、`/redoc`、`/openapi.json` |
| `AGENTOS_API__CORS_ORIGINS` | `[]` | 允许的跨域来源，JSON 数组 |

### 日志（`logging`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_LOGGING__LEVEL` | `INFO` | 日志级别，大小写不敏感 |
| `AGENTOS_LOGGING__FORMAT` | `console` | `console`（人读）或 `json`（采集） |
| `AGENTOS_LOGGING__REDACT_KEYS` | `["api_key","authorization","password","secret","token"]` | 需要脱敏的字段名（大小写不敏感、递归匹配） |

JSON 格式示例：

```json
{"level":"INFO","logger":"agentos.runtime.runtime","message":"agent run completed","request_id":"req_3b84...","run_id":"run_3f2a...","agent":"assistant","iterations":1,"duration_ms":0.161,"total_tokens":12,"timestamp":"2026-09-11T02:34:11.512Z"}
```

### Evaluation（`evaluation`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_EVALUATION__DB_PATH` | `.agentos/evaluations.db` | Evaluation run 持久化路径 |
| `AGENTOS_EVALUATION__MAX_RECORDS` | `1000` | 每个 Workspace 保留的评测记录数 |
| `AGENTOS_EVALUATION__MAX_CONCURRENCY` | `4` | 单次 Dataset 的并发 Case 数 |
| `AGENTOS_EVALUATION__DATASET_ROOT` | `evals` | JSONL Dataset 根目录，API 不允许越界 |
| `AGENTOS_EVALUATION__JUDGE_ENABLED` | `false` | 是否启用 LLM Judge（会产生模型调用费用） |
| `AGENTOS_EVALUATION__JUDGE_MODEL` | 空 | Judge 模型名；为空时使用当前默认模型 |

### Observability（`observability`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_OBSERVABILITY__ENABLED` | `false` | 是否配置 OpenTelemetry tracing |
| `AGENTOS_OBSERVABILITY__SERVICE_NAME` | `agentos` | OTel service.name |
| `AGENTOS_OBSERVABILITY__OTLP_ENDPOINT` | 空 | OTLP HTTP endpoint，例如 `http://collector:4318` |
| `AGENTOS_OBSERVABILITY__EXPORT_TRACES` | `false` | 是否实际导出 trace |
| `AGENTOS_OBSERVABILITY__EXPORT_METRICS` | `false` | 是否启用 OTel metrics exporter |
| `AGENTOS_OBSERVABILITY__SAMPLE_RATIO` | `1.0` | trace 采样比例（0-1） |
| `AGENTOS_OBSERVABILITY__PROMETHEUS_ENABLED` | `false` | 是否开放 `/metrics` |
| `AGENTOS_OBSERVABILITY__METRICS_PATH` | `/metrics` | Prometheus endpoint 路径 |

模型价格配置示例：

```powershell
$env:AGENTOS_LLM__PRICING = '{"your-model":{"prompt_tokens_per_million":0.5,"completion_tokens_per_million":1.5}}'
```

价格只做配置，不内置任何厂商默认值；没有匹配价格的模型，`estimated_cost` 为 `null`。

## 提供方说明

| Provider | 用途 | 必需配置 |
| --- | --- | --- |
| `echo` | 本地开发与测试，回显最后一条用户消息，无外部依赖 | 无 |
| `openai_compatible` | OpenAI、DeepSeek、通义兼容模式、vLLM、Ollama 等 | `BASE_URL`、`MODEL`、通常需要 `API_KEY` |

新增自有提供方：实现 `agentos.llm.base.LLMClient`，然后

```python
from agentos.llm import register_provider

register_provider("my_provider", lambda settings: MyLLMClient(settings))
```

## 多租户与配额

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_PLATFORM__DB_PATH` | `.agentos/platform.db` | User / Workspace / Tool Policy / Quota 元数据 |
| `AGENTOS_QUOTA__DAILY_RUN_LIMIT` | `1000` | Workspace 每日 Run 上限 |
| `AGENTOS_QUOTA__DAILY_TOKEN_LIMIT` | `1000000` | Workspace 每日 Token 上限 |
| `AGENTOS_QUOTA__REQUESTS_PER_MINUTE` | `60` | 每分钟请求上限 |
| `AGENTOS_QUOTA__MAX_ITERATIONS_PER_RUN` | `8` | 单次运行迭代上限 |
| `AGENTOS_QUOTA__MAX_TOOL_CALLS_PER_RUN` | `10` | 单次运行工具调用上限 |

认证成功后绑定 `user_id` / `workspace_id`。Tool 策略和 Quota 都按当前
Workspace 读取，不能通过请求参数跨租户读取。

## 数据库与迁移

数据层统一使用 `database/connection.py` 的 `DatabaseManager`（兼容类名 `Database`）。
每个 SQLite 操作打开短连接，连接时自动确保父目录存在；数据库文件被删除后会重建表结构。
新增数据库或字段时应使用 `database/migrations/`：

```python
from agentos.database import DatabaseManager, Migration

db = DatabaseManager(
    ".agentos/example.db",
    migrations=[
        Migration(1, "create-items", "CREATE TABLE items (id INTEGER PRIMARY KEY);"),
        Migration(2, "add-name", "ALTER TABLE items ADD COLUMN name TEXT;"),
    ],
)
```

`schema_migrations` 账本确保每个版本只执行一次。旧 `agentos.core.database.Database`
导入路径保留为兼容入口，新代码应使用 `agentos.database`。Repository 基座位于
`agentos.database.repository`，业务仓储位于 `agentos.runtime.repositories`。

## 评估模块

`agentos.evaluation` 同时提供旧版工程指标和 Phase 4 质量评估。基础指标包括：

- `latency`：avg / p50 / p95 / max；
- `tokens`：prompt / completion / total / avg_per_run；
- `tool_calls`：合计、均值、单次最多、使用工具的运行数。

`Evaluator` 从 `RunRepository` 读取聚合数据，API 的评估响应保持既有格式；
`Metric` 是可扩展抽象，额外指标可通过 `Evaluator.collect()` 获取。
质量评估支持 JSONL Dataset、规则 Evaluator、工具轨迹、可选 Judge 和回归比较，
详见 [Evaluation Framework](evaluation-framework.md)；工程指标见 [Evaluation](evaluation.md)。

## 安全注意

- `.env` 已被 `.gitignore` 忽略，切勿提交真实密钥
- API Key 使用 `SecretStr` 承载，`model_dump_json()` 输出为 `**********`
- 日志中命中 `redact_keys` 的字段统一替换为 `***`
- `run_command` 默认关闭；开启等于把宿主机 shell 交给模型，请自行评估风险
- 文件工具默认只能操作 `workspace_root`，但仍会读取该项目内的全部源码，注意仓库边界
- `fetch_url` 会访问外网，抓到的内容进入模型上下文，注意提示注入风险
- 搜索 API Key 使用 `SecretStr` 承载，不会出现在工具声明或日志里
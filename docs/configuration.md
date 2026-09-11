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

可重试状态码：`408 409 425 429 500 502 503 504`；重试使用指数退避。
超时映射为 `LLMTimeoutError`（HTTP 504），上游 4xx/5xx 映射为 `LLMProviderError`（HTTP 502）。

### Runtime（`runtime`）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_RUNTIME__DEFAULT_AGENT` | `assistant` | 默认 Agent 名称，`POST /api/v1/runs` 未指定时使用 |
| `AGENTOS_RUNTIME__MAX_ITERATIONS` | `8` | 单次运行的最大迭代轮数（1-64），超出抛 `AgentRuntimeError` |
| `AGENTOS_RUNTIME__SYSTEM_PROMPT` | `You are AgentOS, a helpful AI agent.` | 默认助手的系统提示词 |

### 记忆（`memory`）

会话记忆当前是**进程内短期记忆**：请求带上 `session_id` 即启用，进程重启清空。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_MEMORY__MAX_MESSAGES_PER_SESSION` | `50` | 单会话保留的最大消息条数（1-1000） |
| `AGENTOS_MEMORY__MAX_SESSIONS` | `1000` | 进程内会话数上限，超出按 LRU 淘汰 |

截断按**完整轮次**对齐：只保留从一个 `user` 消息开始的片段，
避免把 `assistant(tool_calls)` 与其后的 `tool` 结果拆散 —— 那样再发给
OpenAI 兼容接口会因为 tool_calls 缺少对应结果而报错。

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

## 安全注意

- `.env` 已被 `.gitignore` 忽略，切勿提交真实密钥
- API Key 使用 `SecretStr` 承载，`model_dump_json()` 输出为 `**********`
- 日志中命中 `redact_keys` 的字段统一替换为 `***`
- `run_command` 默认关闭；开启等于把宿主机 shell 交给模型，请自行评估风险
- 文件工具默认只能操作 `workspace_root`，但仍会读取该项目内的全部源码，注意仓库边界
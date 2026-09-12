# Changelog

本项目的主要变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## 未发布

### 新增

- **Tool Calling（阶段 1 首项）**：模型可通过工具与外部世界交互，Runtime 自动执行工具并回填结果
  - `runtime/tools.py`：`Tool` 抽象基类、`FunctionTool` 快捷封装、`ToolRegistry` 注册表与执行器
  - 参数校验：按工具声明的 JSON Schema 校验 `required` / `type` / `enum`，未引入额外依赖
  - 错误回填：工具不存在、参数非法、执行抛异常都转为 `is_error` 结果回填给模型，不中断整次运行
  - 内置工具：`get_current_time`（按 UTC 偏移返回时间）、`calculate`（AST 白名单算术求值，不使用 `eval`）
  - `llm/base.py`：新增 `ToolSpec` / `ToolCall`，`LLMResponse.tool_calls` 与 `CompletionOptions.tools`
  - `OpenAICompatibleLLMClient`：请求体写入 `tools`，响应解析并归一化 `tool_calls`
  - Runtime 多轮循环：`_should_continue` 检测到工具调用即继续，`max_iterations` 兜底并记录 `tool_call_count`
  - API：新增 `GET /api/v1/tools`，`Agent.tools` 字段贯通注册与运行，`/health/ready` 返回工具数量
- **可观测性：trace 贯穿与审计日志**
  - 新增 `trace_id` / `tool_name` / `actor` 三个上下文字段，
    与既有 `request_id` / `run_id` / `agent_name` 一起构成完整链路
  - 上下文新增 `bind()` 上下文管理器，支持一次绑定多个字段并自动按相反顺序还原；
    字段名拼错直接抛 `ValueError`，不静默忽略
  - 请求中间件生成或透传 `X-Trace-ID`，响应头回显；
    整段请求都在绑定内，访问日志因此也带上 trace_id
  - 工具执行期间绑定 `tool_name`，一次运行调多个工具时日志不再混在一起
  - 认证中间件在密钥匹配后绑定 `actor`（密钥的 SHA-256 前 12 位，不可反推）
  - 新增 `runtime/audit.py` 与 `audit_logs` 表：记录「谁、什么时候、
    对什么做了什么、结果如何」，四个动作 `agent.run` / `tool.execute` /
    `agent.register` / `agent.unregister`
  - 审计的上下文字段**全部自动从 contextvars 取**，调用方只需说明做了什么
  - 新增 `GET /api/v1/audit`，支持按 action / actor / run_id / status 过滤与排序
  - 新增 `docs/observability.md`
- **数据持久化层重构**：统一 Database + Repository 两层
  - `core/database.py`：`Database` 统一管理连接、建目录、建表与事务
    —— 之前三个存储各写了一份 `mkdir + connect + executescript` 的重复逻辑
  - `runtime/repositories.py`：`AgentRepository` / `RunRepository` / `MemoryRepository`
    把 SQL 与「行 ↔ 模型」的转换从业务对象里搬出来
  - 三个存储改为薄外壳：只保留业务语义（重名冲突、容量淘汰、检索词抽取），
    **公开接口完全不变**，既有导入路径（`RunRecord` / `MemoryRecord`）也照常可用
- **Agent 注册表默认持久化**：`AGENTOS_REGISTRY__PERSIST` 默认改为 `true`，
  Agent 定义开箱即落盘 SQLite，不再需要显式开启
- **运行历史支持排序**：`GET /api/v1/runs?order=asc|desc`（默认 `desc` 最新在前）
- **Evaluation 基础模块**：
  - `runtime/evaluation.py`：基于运行记录聚合四类指标
    - 延迟：avg / p50 / p95 / max（线性插值分位数）
    - token：prompt / completion / total / 每次运行均值
    - 成功率：completed / 总数
    - 工具调用：合计 / 均值 / 单次最多 / 多少运行用了工具
  - `GET /api/v1/evaluation/summary`：支持按 `agent` 与 `since` 圈定范围
  - 刻意**不做质量评估**（回答好坏、是否幻觉）—— 那需要评测集与裁判模型，属后续阶段
- **SQLite 存储的健壮性修复**：目录或文件被外部删除后自动恢复
  - 此前三个存储（runs / memory / registry）只在 `__init__` 里建目录，
    运行期间手工清空 `.agentos/` 会让后续所有操作报
    `sqlite3.OperationalError: unable to open database file`（接口直接 500）
  - 改为每次连接都确保父目录存在；数据库文件是新建的则重建表结构
  - 覆盖两种场景：目录被删、只删 db 文件
- **运行记录持久化与历史查询**：解决「跑完就查不到」
  - `runtime/run_store.py`：`RunStore` / `RunRecord`，落盘 SQLite
  - 结构化字段（agent / session_id / status / created_at / tokens）建列用于过滤排序，
    完整结果序列化进 `payload` 列，避免给 `RunResult` 加字段就改表
  - **成功与失败都记录** —— 失败的运行同样需要留痕
  - 容量上限 `max_records`（默认 10000），超出按时间淘汰最旧的
  - Runtime 在 `run_stream` 成功/异常分支分别写入，两种运行方式都能覆盖
  - API：新增 `GET /api/v1/runs`（分页 + agent/session/status 过滤）
    与 `GET /api/v1/runs/{run_id}`（含完整消息轨迹）
- **Swagger UI 支持 API Key 认证**：浏览器里也能验证接口
  - 认证是中间件实现的，路由上没有声明依赖，FastAPI 不会自动生成
    `securitySchemes`，Swagger UI 也就没有地方填 Key，点任何接口都只能拿到 401
  - 新增 `install_api_key_security_scheme()`：手动注入 `APIKeyHeader` 安全方案，
    让 Swagger 出现 **Authorize** 按钮
  - 未开启认证时不注入，避免给免认证部署造成误导
  - `AGENTOS_AUTH__HEADER_NAME` 会同步反映到安全方案里
- **JSON 响应补上 charset**：修复 PowerShell 5.1 读接口中文乱码
  - 根因：Starlette 只在 `text/*` 上自动补 charset，`application/json` 不带；
    而 PS 5.1 的 `Invoke-WebRequest` 在没有 charset 时按 **ISO-8859-1** 解码
  - 新增 `JSONCharsetMiddleware`，统一给 `application/json` 响应补 `charset=utf-8`
  - 用中间件而不是自定义响应类：FastAPI 内置的 `/openapi.json` 直接返回
    `JSONResponse`，绕过 `default_response_class`，只有中间件能覆盖
  - 现在 `(Invoke-WebRequest $url -UseBasicParsing).Content` 直接可用，
    不再需要手动 `[System.Text.Encoding]::UTF8.GetString(...)`
- **Agent 持久化**：Agent 定义落盘 SQLite，重启不再丢失
  - `runtime/sqlite_registry.py`：`SQLiteAgentRegistry`，接口与内存版一致
  - 存储用 JSON payload 列而非逐字段建列，避免 Agent 模型演进时频繁改表
  - `runtime/registry.py` 抽出 `build_registry()`，按 `persist_path` 决定实现
  - 默认 Agent 缺失时补种，已存在的不覆盖（自定义不会被重启冲掉）
  - 删除同样持久化，避免「删掉的 Agent 重启后复活」
  - 新增 `RegistrySettings`：`AGENTOS_REGISTRY__PERSIST` / `__DB_PATH`
- **API Key 认证**：补齐最关键的鉴权缺口（此前任何客户端都能读全部会话与记忆）
  - `api/auth.py`：`APIKeyMiddleware`，纯 ASGI 实现，统一拦截所有 HTTP 请求
  - **默认关闭**，本地开发不受影响；对外暴露时设置 `AGENTOS_AUTH__ENABLED=true`
  - **失败关闭**：开启但未配置密钥时拒绝所有请求，配置失误不会变成安全漏洞
  - **常量时间比较**（`secrets.compare_digest`），避免通过响应时间反推密钥
  - 放行 `OPTIONS` 预检与健康探针 / 文档路径
  - 中间件顺序调整：CORS → 请求上下文 → 认证 → 路由，401 也带 `request_id` 并进访问日志
- **Multi-Agent（多 Agent 协作与消息路由）**：
  - 把 Agent 暴露成工具：新增 `delegate_to_agent`，主 Agent 可把子任务交给专门角色
  - `runtime/agent_tools.py`：`DelegateToAgentTool`，工具描述**运行时动态列出可用 Agent**
  - **深度限制**：委托链最多 3 层，深度存 `contextvars`，并发运行独立计数
  - **子 Agent 无状态运行**：父级需给出自包含任务，子 Agent 不读写父级会话记忆，避免上下文污染
  - 拒绝自我委托（A 委托给 A），避免无意义递归
  - `AgentRuntime` 新增 `enable_delegation` / `max_delegation_depth` 配置
  - API 的 `ToolSummary` 改用 `tool.spec()`，展示模型真正看到的动态描述
- **Planning（任务分解与执行计划）**：Agent 动手前先拆解任务并跟踪进度
  - `runtime/planning.py`：`ExecutionPlan` / `PlanStep` / `StepStatus`，
    计划存在 `contextvars` 里，**天然按运行隔离**，并发运行互不干扰
  - `runtime/plan_tools.py`：`create_plan` / `update_plan_step` 两个工具
  - Runtime 在**每轮调用模型前**把当前计划并入系统提示词，模型始终看得到进度
  - `RunResult.plan` 与 `RunResponse.plan` 暴露最终计划，便于观测
- **流式回复**：`POST /api/v1/runs/stream` 以 SSE 逐段推送
  - `llm/base.py`：新增 `StreamChunk` 与 `LLMClient.stream()`；
    默认实现退化为一次性返回，不支持流式的提供方无需改动
  - `OpenAICompatibleLLMClient.stream()`：解析 SSE，`tool_calls` 分片按 `index` 聚合，
    并请求 `stream_options.include_usage` 以拿到 token 用量
  - `AgentRuntime.run_stream()`：产出 `start` / `delta` / `tool_call` / `tool_result` / `end` / `error` 事件
  - `AgentRuntime.run()` 重构为 `run_stream()` 的薄封装，消除两份执行循环
  - 文本增量**边收边发**，不做整段缓冲
- **长期记忆**：跨会话持久化的记忆存储与检索
  - `runtime/long_term_memory.py`：基于 SQLite 的 `LongTermMemory`，进程重启不丢
  - 检索用关键词加权匹配：查询切成英文词与中文二元组，按命中词长度排序
    （SQLite 内置 FTS5 对中文支持差，两个字的中文词都召不回，故不走 FTS）
  - `runtime/memory_tools.py`：`remember` / `recall` 两个工具，由模型自行决定记什么
  - Runtime 新增自动召回：运行前把相关记忆并入系统提示词
  - API：新增 `GET/POST/DELETE /api/v1/memories`
  - 数据库默认落在 `.agentos/memory.db`，已加入 `.gitignore`
- **联网工具**：Agent 可以抓取网页与联网检索
  - `runtime/web_tools.py`：`fetch_url`（网页转纯文本）与 `web_search`（Tavily 兼容搜索）
  - `fetch_url` 带 SSRF 防护：仅允许 http/https，且目标必须解析到公网地址；
    回环、内网、链路本地、保留地址（含云元数据 `169.254.169.254`）全部拒绝
  - 重定向逐跳重新校验，避免「先给公网地址再 302 到内网」绕过
  - HTML 用标准库 `html.parser` 转纯文本，跳过 script/style，不引入新依赖
  - `web_search` 仅在配置 `AGENTOS_TOOLS__WEB_SEARCH_API_KEY` 时注册
  - `truncate_text` 提取为公共工具函数，供本地工具与联网工具复用
- **会话短期记忆**：Agent 可在多轮对话中记住上下文，**默认开启**
  - `runtime/memory.py`：`MemoryStore` 进程内实现，按 `session_id` 隔离会话
  - 不传 `session_id` 时落到默认会话 `default`，开箱即用；
    把 `AGENTOS_MEMORY__DEFAULT_SESSION_ID` 设为空字符串可恢复无状态
  - 优先级：显式 `session_id` > 显式 `history`（调用方自行管理）> 默认会话
  - 双容量约束：单会话消息数上限 + 全局会话数 LRU 淘汰
  - 截断按完整轮次对齐，避免拆散 `assistant(tool_calls)` 与 `tool` 结果
  - Runtime 新增 `session_id` 参数与 `RunResult.session_id`
  - API：`RunRequest.session_id`，新增 `GET/DELETE /api/v1/sessions`
- **本地工具集**：让 Agent 具备编码助手式的文件与命令能力
  - `runtime/sandbox.py`：`WorkspaceSandbox` 路径沙箱（拒绝 `..` 逃逸、外部绝对路径、
    指向外部的符号链接）与敏感文件黑名单（`.env`、私钥、API Key、`secrets/` 等）
  - `runtime/local_tools.py`：`list_directory` / `read_file` / `search_text` / `write_file` / `run_command`
  - `write_file` 默认拒绝覆盖已有文件，需模型显式传入 `overwrite=true`
  - `run_command` **默认关闭**，需 `AGENTOS_TOOLS__ALLOW_SHELL=true` 显式开启，带超时与输出截断
  - 新增 `ToolsSettings` 配置段：沙箱根目录、写/命令开关、读取与输出限额
  - 工具注册表按配置动态生成，未启用的能力不会出现在暴露给模型的工具列表中
- `examples/qwen_smoke.py`：真实模型冒烟测试脚本，走「配置 → LLM 客户端 → Agent Runtime」全链路，
  输出耗时与 token 消耗，支持 `--model` / `--models` 切换模型
- `.vscode/tasks.json`：VS Code 一键任务（启动服务、热重载、真实模型冒烟、测试、代码检查、安装依赖）
- `.vscode/settings.json`：默认解释器指向 `.venv`，启用 pytest 面板
- `.gitattributes`：统一换行符为 LF，避免跨平台无意义 diff

### 修改

- `.env.example` 补充阿里云百炼 / DashScope OpenAI 兼容模式与专属工作空间（MaaS）配置示例

### 安全

- `.gitignore` 新增密钥文件忽略规则：`*apiKey*.csv`、`*apikey*.csv`、`*-apiKey-*.*`、`secrets/`

### 技术记录

- Tool Calling 采用「模型决策 + 服务端执行」分离：模型只返回工具名与 JSON 参数，
  执行与校验全部在 `runtime` 层完成，`llm` 层只做协议编解码，保持依赖方向 `api → runtime → llm` 不变
- 工具参数用 JSON Schema 声明，只校验 `required` / `type` / `enum` 子集，避免为此引入 `jsonschema` 依赖
- 工具执行失败不抛异常而是回填错误文本，让模型有机会自我修正，同时保证单次工具故障不拖垮整个会话
- 内置时间工具刻意使用 `datetime.timezone` 固定偏移而非 `zoneinfo`：后者在 Windows 上需要额外的 `tzdata` 包
- 测试增至 97 个用例，新增 `tests/test_tools.py`（34 个）并扩展 Runtime / API / LLM 客户端的工具调用覆盖
- 本地工具采用「路径沙箱 + 敏感文件黑名单」双重防护；符号链接逃逸由 `Path.resolve()` 一并覆盖
- `run_command` 不做沙箱（shell 内部可访问任意路径），只能靠默认关闭 + 超时 + 输出截断降低风险
- 搜索遇到敏感文件时静默跳过而非报错，避免单个 `.env` 让整次搜索失败
- 测试增至 132 个用例，新增 `tests/test_local_tools.py`（35 个）覆盖沙箱、限额与命令开关
- 会话记忆只在运行**成功**时写回，失败运行不会污染历史；系统提示词不写入记忆
- 测试增至 157 个用例，新增 `tests/test_memory.py`（25 个）覆盖存储、LRU、截断与 API
- 联网抓取用 `httpx.MockTransport` 注入测试，SSRF 用例断言恶意地址**根本不会发起请求**
- 测试增至 196 个用例，新增 `tests/test_web_tools.py`（39 个）覆盖 SSRF、HTML 转换与搜索
- 默认会话开启后，显式传 `history` 的调用方会被优先尊重，避免破坏「客户端自管历史」的既有用法
- 测试增至 199 个用例，补充默认会话、关闭默认会话与 history 优先级用例
- 长期记忆用 SQLite 连接时显式 close：`with sqlite3.connect(...)` 只管理事务，不关闭连接，会泄漏句柄
- 测试夹具把长期记忆库重定向到 `tmp_path`，避免跑测试时在工作区生成 `.agentos/memory.db`
- 测试增至 232 个用例，新增 `tests/test_long_term_memory.py`（33 个）
- 流式请求不做重试：一旦开始接收数据，重放会导致内容重复
- SSE 响应带 `x-accel-buffering: no`，避免反向代理缓冲导致「流式看起来不流式」
- 测试增至 248 个用例，新增 `tests/test_streaming.py`（16 个）
- 计划注入放在**每轮循环开头**而不是运行开始：模型可能在上一轮才创建计划，
  只注入一次会导致后续轮次看不到计划
- 测试增至 271 个用例，新增 `tests/test_planning.py`（23 个）
- 委托工具必须在 Runtime 实例化过程中注册（它要引用 Runtime 自身），
  因此默认 Agent 的工具清单改为在委托工具注册**之后**再生成
- 测试增至 289 个用例，新增 `tests/test_multi_agent.py`（18 个）
- 认证放在**请求上下文内层**：`add_middleware` 后加的先执行，因此先 add 认证、
  再 add 请求上下文，401 响应才能带上 request_id 并写入访问日志
- 测试增至 307 个用例，新增 `tests/test_auth.py`（18 个）
- SQLite 注册表同样显式关闭连接；`with sqlite3.connect(...)` 只管理事务不关连接
- 测试增至 327 个用例，新增 `tests/test_sqlite_registry.py`（20 个）
- charset 中间件放在**最外层**，确保所有内层响应（含异常处理与内置路由）都被覆盖
- 测试增至 337 个用例，新增 `tests/test_responses.py`（10 个）
- 安全方案的注入用包装 `app.openapi` 实现，保持幂等；OpenAPI 本身仍走 charset 中间件
- 测试增至 342 个用例，`tests/test_auth.py` 补充 5 个 Swagger 相关用例
- `RunStore` 与 `RunResult` 之间用 `TYPE_CHECKING` 隔离，避免 run_store 与 runtime 循环导入
- 列表接口不返回消息列表，避免历史查询把上下文撑爆；详情接口才带完整轨迹
- 测试增至 364 个用例，新增 `tests/test_run_store.py`（22 个）
- 测试增至 366 个用例，补充「目录被删」「db 文件被删」两个恢复场景
- Repository 只依赖 `Database`，三个存储只依赖各自的 Repository，分层后
  SQL 不再散落在业务对象里
- 计数与合计走 SQL 聚合，分位数需要具体数值所以单独取耗时列
- 测试增至 411 个用例，新增 `tests/test_database.py`（29 个）与 `tests/test_evaluation.py`（16 个）
- 审计与运行记录分表存储：前者面向追责（量小、固定字段），后者面向排查（量大、含消息轨迹）
- 测试增至 447 个用例，新增 `tests/test_observability.py`（14 个）与 `tests/test_audit.py`（22 个）
- 新增 autouse 夹具 `isolate_data_paths`：用环境变量把 runs / memory / registry
  三个落盘路径统一重定向到 `tmp_path`；只改 `settings` 夹具挡不住那些
  自行构造 `Settings(_env_file=None)` 的用例，仍会往工作区 `.agentos/` 写数据
- 实测链路：Qwen3.8-Max（自定义 API）通过 OpenAI 兼容协议接入，`POST /api/v1/runs` 端到端往返约 3.6 秒，
  单轮对话 186 tokens，注册自定义 Agent（code-reviewer）后可直接复用同一 Runtime
- 注意事项：百炼控制台下载的 CSV 里 `dashScope` 是原生端点（`/api/v1`），
  AgentOS 需要的是 `openAiCompatible` 端点（`/compatible-mode/v1`）

## 0.1.0 - 2026-09-11

### 新增

- 工程结构：`src` 布局、`pyproject.toml`（setuptools 打包、ruff 与 pytest 配置）、`agentos` 命令行入口
- FastAPI 服务：`create_app` 装配、lifespan 资源管理、统一错误响应、CORS 可选配置
- HTTP 接口：`/health`、`/health/ready`、Agent 注册/查询/列表/注销、`POST /api/v1/runs` 运行接口
- Agent Runtime 骨架：`Agent`、`Message`、`AgentRegistry`、`AgentRuntime`、`RunResult`，含迭代上限保护与用量统计
- LLM 抽象层：`LLMClient` 契约、`EchoLLMClient` 本地客户端、`OpenAICompatibleLLMClient`（重试、超时与错误映射）
- LLM 工厂：provider 注册表，内置 `echo` / `openai_compatible` / `openai`
- 配置管理：基于 pydantic-settings 的三级覆盖，支持嵌套环境变量与 `SecretStr` 密钥
- 日志系统：console / json 双格式、contextvars 请求上下文注入、敏感字段递归脱敏、请求访问日志
- 请求上下文中间件：生成并透传 `X-Request-ID`，使 API 日志与 Runtime 日志串联
- 测试：49 个用例覆盖配置、日志、LLM 客户端、Runtime 与 API
- 文档：README 重写，新增 `docs/architecture.md`、`docs/configuration.md`、`docs/development.md` 与 `.env.example`

### 修改

- README.md 从占位说明升级为完整项目说明（能力矩阵、架构图、快速开始、API 一览）
- TODO.md 阶段 0「工程基座」任务标记完成，补充后续迭代项

### 修复

- 无

### 技术记录

- 采用 `src` 布局 + Pydantic v2 模型作为层间契约，保证依赖方向单向：`api → runtime → llm`，`core` 横切复用
- LLM 层用注册表工厂解耦 provider 名称与实现，新增模型服务无需改动调用方
- 日志使用标准库 `logging` + `contextvars`，不引入第三方日志依赖，同时让 request_id / run_id 自动贯穿全链路
- 上游错误统一映射：超时 → `LLMTimeoutError`(504)，可重试状态码按指数退避重试，其余上游错误 → `LLMProviderError`(502)
- 本地链路验证：`echo` 提供方 + `agentos serve` 冒烟通过，`POST /api/v1/runs` 返回 `run_id`、用量与耗时

### 下一步计划

- Tool Calling：工具注册表、参数校验、调用结果回填（`AgentRuntime._should_continue` 扩展点）
- Memory：会话记忆与长期记忆存储
- 持久化：Agent 定义与运行记录落库
- 可观测性：指标与链路追踪接入
- 容器化与 CI 部署（需确认后接入）

[0.1.0]: https://github.com/Tanglies/AgentOS/releases/tag/v0.1.0
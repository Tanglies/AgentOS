# 架构设计

## 分层与依赖方向

```
┌─────────────────────────────────────────────────────┐
│ api       FastAPI 装配 / 中间件 / 路由 / DTO         │
├─────────────────────────────────────────────────────┤
│ runtime   Agent / Message / AgentRuntime / Store     │
├─────────────────────────────────────────────────────┤
│ evaluation Metrics / Collector / Report              │
├─────────────────────────────────────────────────────┤
│ database  SQLite / Repository / Migration             │
├─────────────────────────────────────────────────────┤
│ llm       LLMClient 抽象 / 具体实现 / 工厂             │
├─────────────────────────────────────────────────────┤
│ core      配置 / 日志 / 上下文 / 异常                  │
└─────────────────────────────────────────────────────┘
```

依赖方向严格自上而下：`api → runtime → llm`；`database` 只依赖 `core`，`evaluation`
只依赖 `runtime`，`core` 作为横切基础被各层复用。反向依赖（如 `core` 引用 `api`）被禁止。

## 模块职责

| 模块 | 路径 | 职责 |
| --- | --- | --- |
| 配置 | `core/config.py` | `Settings` 定义与加载优先级；嵌套配置用 `__` 分隔 |
| 日志 | `core/logging.py` | console / json 格式化、上下文注入、敏感字段脱敏 |
| 上下文 | `core/context.py` | `contextvars` 承载 request_id / run_id / agent |
| 异常 | `core/exceptions.py` | 统一异常基类，携带 `code` 与 HTTP `status_code` |
| 消息模型 | `runtime/message.py` | 运行期消息（角色、内容、元数据、时间戳） |
| Agent | `runtime/agent.py` | Agent 定义与消息组装 |
| 注册表 | `runtime/registry.py` | 进程内 Agent 注册与查询 |
| 工具基座 | `runtime/tools.py` | `Tool` 抽象、`ToolRegistry` 注册与执行、JSON Schema 子集校验 |
| 内置工具 | `runtime/builtin_tools.py` | 通用工具与默认工具注册表工厂 |
| 路径沙箱 | `runtime/sandbox.py` | 把文件操作约束在 `workspace_root` 内，并拦截敏感文件 |
| 本地工具 | `runtime/local_tools.py` | 目录浏览、文件读写、文本搜索、命令执行 |
| 联网工具 | `runtime/web_tools.py` | 网页抓取（SSRF 防护）与联网搜索 |
| 运行内核 | `runtime/runtime.py` | 迭代调用模型、统计用量、产出 `RunResult` |
| 会话记忆 | `runtime/memory.py` | 按 `session_id` 保存短期记忆，含 LRU 淘汰与轮次对齐截断 |
| 长期记忆 | `runtime/long_term_memory.py` | SQLite 持久化 + 关键词加权召回，跨会话保留 |
| 执行计划 | `runtime/planning.py` | 运行期计划模型 + `contextvars` 隔离 |
| 计划工具 | `runtime/plan_tools.py` | `create_plan` / `update_plan_step` |
| 多 Agent | `runtime/agent_tools.py` | `delegate_to_agent`：把 Agent 暴露成工具，含深度限制 |
| LLM 契约 | `llm/base.py` | `LLMMessage` / `LLMResponse` / `StreamChunk` / `LLMClient` |
| LLM 实现 | `llm/echo.py`, `llm/openai_compatible.py` | 回显客户端与 OpenAI 兼容 HTTP 客户端 |
| LLM 工厂 | `llm/factory.py` | provider 注册表与实例化 |
| 应用装配 | `api/app.py` | lifespan 建资源、挂载中间件、路由与异常处理 |
| 认证 | `api/auth.py` | `APIKeyMiddleware`：静态/数据库密钥校验、失败关闭、身份绑定 |
| API Key | `runtime/api_keys.py` | 密钥哈希、权限模型、签发、校验与吊销 |
| 权限依赖 | `api/deps.py` | `require(permission)` 路由级鉴权；认证关闭时放行 |
| 数据库连接 | `database/connection.py` | `Database` / `DatabaseManager`：连接、建目录、建表与迁移账本 |
| 迁移机制 | `database/migrations/` | `Migration` 与 `MigrationRunner`，按版本幂等应用 |
| Repository 基座 | `database/repository.py` | `Repository`、`:func:`build_filter`` 与共享参数化查询工具 |
| 持久化模型 | `database/models.py` | `SchemaMigration`、`Pagination` 等跨仓储模型 |
| 评估指标 | `evaluation/metrics.py` | latency / token / tool-call 指标与可扩展 `Metric` 抽象 |
| 评估采集 | `evaluation/collector.py` | `Evaluator` / `EvaluationCollector` |
| 评估报告 | `evaluation/report.py` | `EvaluationReport` 的 JSON 与 Markdown 格式化 |
| 持久化注册表 | `runtime/sqlite_registry.py` | `SQLiteAgentRegistry`：Agent 定义落盘 |
| 运行记录 | `runtime/run_store.py` | `RunStore`：运行历史落盘，支持过滤分页 |
| 审计日志 | `runtime/audit.py` | `AuditLog`：谁/何时/做了什么/结果，上下文字段自动捕获 |

## 一次运行的调用链

```
Client
  │  POST /api/v1/runs
  ▼
RequestContextMiddleware        生成 request_id，写入 X-Request-ID
  ▼
runs.create_run                 解析请求，选择 Agent
  ▼
AgentRuntime.run                绑定 run_id；有 session_id 时从 MemoryStore 取历史
  ▼
LLMClient.complete              调用模型（echo 或 OpenAI 兼容，携带 tools 声明）
  ▼
模型是否返回 tool_calls？
  ├─ 是 → ToolRegistry.execute  校验参数 → 执行工具 → 结果作为 tool 消息回填
  │        └─ 再次调用模型（循环受 max_iterations 约束）
  └─ 否 → 得到最终回答
  ▼
RunResult                       输出 + 用量 + 耗时 + tool_call_count → RunResponse
```

日志示例（console 格式）：

```
2026-09-11 10:34:11 INFO agentos.runtime.runtime - agent run completed | request_id=req_3b84... run_id=run_3f2a... agent=assistant iterations=1 duration_ms=0.161 total_tokens=12
```

## 关键设计决策

| 决策 | 原因 |
| --- | --- |
| `llm` 层定义协议无关的消息模型 | Runtime 不依赖任何厂商 SDK，替换模型服务不影响上层 |
| provider 注册表工厂 | 新增模型服务只需实现 `LLMClient` 并 `register_provider`，无需改动调用方 |
| 标准库 `logging` + `contextvars` | 不引入第三方日志依赖，同时让 request_id / run_id 自动贯穿全链路 |
| 异常携带 `status_code` / `code` | API 层集中转换，错误语义稳定且可被客户端程序化处理 |
| 资源在 lifespan 中创建 | 避免模块导入即建立外部连接，便于测试与多进程部署 |
| 纯 ASGI 中间件 | 规避 `BaseHTTPMiddleware` 的额外任务与流式响应问题 |
| 工具参数只校验 JSON Schema 子集 | 只覆盖 `required` / `type` / `enum`，避免为此引入 `jsonschema` 依赖 |
| 工具执行失败回填而非抛出 | 让模型有机会自我修正参数，单次工具故障不中断整次会话 |
| 文件工具统一走路径沙箱 | 模型可能被提示注入诱导读写任意路径，沙箱把影响面限制在 `workspace_root` |
| 敏感文件黑名单 | 避免 `.env`、私钥等凭据被读进模型上下文或写入日志 |
| `run_command` 默认关闭 | shell 无法被路径沙箱约束，只能用显式开关 + 超时 + 输出截断降低风险 |
| 联网抓取做 SSRF 防护 | 模型可被诱导抓取云元数据地址窃取凭据，必须限制为公网目标并逐跳校验重定向 |
| 记忆靠 `session_id` 显式启用 | 不传即无状态，保持向后兼容，也避免无意义的会话堆积 |
| 记忆截断对齐完整轮次 | 拆散 `tool_calls` 与 `tool` 结果会让上游接口直接报错 |
| 长期记忆用关键词而非向量 | 向量检索要引入 embedding 依赖与额外调用；关键词匹配用标准库即可覆盖常见召回 |
| `run()` 是 `run_stream()` 的封装 | 避免两份执行循环；流式与非流式的记忆、工具、迭代语义天然一致 |
| 流式默认实现退化为一次性返回 | 不支持流式的提供方无需改动即可接入，能力逐级增强 |
| 流式不做重试 | 已开始接收数据后重放会导致内容重复 |
| 执行计划用 `contextvars` 存储 | 按运行自动隔离，并发安全，无需显式清理 |
| 计划每轮重新注入 | 模型可能中途才创建或更新计划，只注入一次会看不到进度 |
| Agent 以工具形式暴露 | 复用既有的工具调用链路做消息路由，不需要另造一套编排引擎 |
| Agent 用 JSON 列存储 | Agent 定义仍在演进，JSON 列免去频繁改表结构 |
| 运行记录同时建索引列与 JSON 列 | 索引列用于过滤排序，JSON 列承载完整结果 |
| 运行列表不返回消息 | 历史查询只关心摘要，完整轨迹按需取详情 |
| 上下文字段用 `contextvars` | 异步链路自动传递，无需逐层透传参数 |
| 审计与运行记录分表 | 前者面向追责（量小固定），后者面向排查（量大含轨迹） |
| 审计记录调用方身份而非原文 | 数据库密钥用名称，静态密钥用不可反推指纹 |
| 注册表持久化默认关闭 | 内存实现零依赖、启动即用；需要跨重启保留时再开启 |
| 显式迁移账本 | 只靠 `CREATE TABLE IF NOT EXISTS` 无法表达字段变更，`schema_migrations` 可按版本幂等执行 |
| 评估与运行记录解耦 | 采集器只依赖 `RunRepository`，未来可以替换统计源或增加自定义 `Metric` |
| 认证默认关闭 | 本地开发的便利性优先；对外暴露时由部署方显式开启 |
| 认证失败关闭 | 开启但没配密钥时拒绝一切，避免配置失误变成未授权访问 |
| 认证位于请求上下文内层 | 401 响应也能带 `request_id` 并写入访问日志，便于排查 |
| 数据库密钥只存哈希 | 密钥是高熵随机值，SHA-256 足够抵抗反推且适合每请求校验 |
| 静态配置密钥只作管理员引导 | 新部署没有任何数据库密钥时仍需一个可签发第一把钥匙的入口 |
| 路由权限 + 工具执行权限双重检查 | 防止绕过 HTTP 路由或模型直接构造工具调用 |
| 子 Agent 无状态运行 | 父子共用会话记忆会让两个上下文互相污染，任务自包含更可预测 |

## 扩展点

- **新增模型服务**：实现 `LLMClient` → `register_provider("name", factory)` → 配置 `AGENTOS_LLM__PROVIDER=name`
- **新增工具**：继承 `Tool` 声明 `name` / `description` / `parameters` → 注册进 `ToolRegistry` → 在 `Agent.tools` 中引用
- **工具调用链路**：`AgentRuntime._should_continue` 检测 `tool_calls` → `ToolRegistry.execute` 校验并执行 → 结果回填后再次调用模型
- **持久化 Agent**：`AgentRegistry` 接口保持不变，替换为数据库实现即可
- **新增路由**：在 `api/routes/` 下新增模块，并在 `api/app.py` 挂载
- **外部日志采集**：`AGENTOS_LOGGING__FORMAT=json` 输出 JSON 行，直接被 Fluent Bit / Loki 等采集

## v0.1 边界

阶段 1 已全部完成（Tool Calling、Planning、短期与长期记忆、Multi-Agent 委托、流式回复），
阶段 2 已完成 SQLite 持久化结构对齐、迁移账本、Repository 基座、API Key 权限与工具执行鉴权；
阶段 3 已完成基础 Evaluation 与审计/链路追踪。**尚未实现**：用户账号与工作区隔离、
配额与限流、向量检索、评测集与自动评分、Prometheus/OpenTelemetry 导出与容器化部署。这些能力按 `TODO.md` 的阶段推进，接入时保持既有分层与接口不变。
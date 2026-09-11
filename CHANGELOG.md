# Changelog

本项目的主要变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
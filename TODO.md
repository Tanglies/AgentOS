# TODO

AgentOS 的开发任务清单。按优先级从上到下推进，每个任务都应「小而完整、当天可验证」。

## 阶段 0：工程基座 ✅ v0.1.0

- [x] 确定技术栈与项目结构（Python 3.11+ / FastAPI / Pydantic v2 / src 布局）
- [x] 建立包管理配置（pyproject.toml，支持可编辑安装与 `agentos` 命令）
- [x] 配置测试框架与本地运行命令（pytest + ruff + `agentos serve`）
- [x] 基础日志模块（console / json、请求上下文、敏感字段脱敏）
- [x] LLM 客户端抽象与 echo / OpenAI 兼容实现
- [x] 配置管理与健康探针
- [x] 测试与文档基线

## 阶段 1：Agent 核心能力

- [x] Tool Calling：工具注册表、参数校验、调用与结果回填（Runtime 已预留 `_should_continue` 扩展点）
  - 已实现：`Tool` 抽象 / `ToolRegistry` / JSON Schema 子集校验 / 错误回填 / 多轮循环 / `GET /api/v1/tools`
  - 内置工具：`get_current_time`、`calculate`；自定义工具只需继承 `Tool` 并在注册表登记
  - 本地工具：`list_directory`、`read_file`、`search_text`、`write_file`、`run_command`
    （文件工具受沙箱与敏感文件黑名单约束，命令执行默认关闭）
  - 联网工具：`fetch_url`（带 SSRF 防护）、`web_search`（需配置搜索 API Key）
- [x] Planning：任务分解与执行计划（`create_plan` / `update_plan_step` + 每轮注入）
- [x] Memory：会话内短期记忆（进程内 `session_id` 维度，含 LRU 淘汰与轮次对齐截断）
- [x] Memory：长期记忆存储与检索（SQLite 持久化 + 关键词召回；向量检索待后续）
- [x] Multi-Agent：多 Agent 协作与消息路由（`delegate_to_agent` + 深度限制 + 子 Agent 隔离）

## 阶段 2：平台能力

- [x] Agent 持久化（`SQLiteAgentRegistry`，**默认开启**；结构化字段 + payload 兼容）
- [x] Agent 生命周期管理（`AgentService`；创建、分页列表、详情、删除）
- [x] Agent 管理 API（`GET/POST/DELETE /api/v1/agents`，支持 `page/page_size`）
- [x] 运行记录持久化与历史查询（`RunStore` + `GET /api/v1/runs`，含过滤、双分页兼容、排序与 `token_usage`）
- [x] Dashboard 只读接口（`overview` / `tools` / `errors`，数据复用 runs / audit / registry）
- [x] Tool 管理（注册、分类、权限绑定）
  - [x] `Tool.required_permissions`：默认要求 `tool:execute`，Runtime 执行点强制校验
- [x] 平台身份 / Workspace 模型：User、Workspace、Membership 与请求上下文
- [x] 资源隔离：Agent / Run / Memory / API Key / Audit 按 Workspace 过滤
- [x] 数据归属：`workspace_id` 已绑定核心资源，查询强制过滤
- [x] 配额与限流：按 Workspace 统计调用量、tokens 与请求速率
- [x] 工具访问控制：Workspace / Agent Tool Policy + Runtime 二次校验
- [ ] **End-user login system（尚未完成）**
  - [ ] username / password 注册与登录（密码哈希采用 bcrypt 或 argon2）
  - [ ] JWT / server-side session 令牌，替代面向终端用户的静态 API Key
  - [ ] 登录态、密码重置、会话撤销与安全审计
- [~] API 完善（分页、过滤、批量操作）
  - [x] Agent 管理 API：分页、过滤条件、完整详情
  - [x] Run History：`page/page_size` 与旧 `limit/offset` 兼容
  - [ ] 批量操作与通用游标分页
- [x] 数据模型与迁移机制
  - [x] 统一 `database` 模块 + Repository 基座（`database/connection.py`、`database/repository.py`、`runtime/repositories.py`）
  - [x] schema 版本表与增量迁移基础（`database/migrations/`，支持按版本幂等执行）

## 阶段 3：多租户平台 ✅ Phase 3

- [x] User / Workspace / Workspace Member 模型与 Repository
- [x] UserService / WorkspaceService / Workspace API
- [x] 请求上下文增加 `user_id` / `workspace_id`
- [x] Agent / Run / Memory / API Key / Audit Workspace 隔离
- [x] 长期 Memory 支持 `user` / `workspace` scope
- [x] Tool Metadata、Workspace/Agent Tool Policy 与双层鉴权
- [x] Quota、Usage、Rate Limit 与 429 错误
- [x] Dashboard / Evaluation 按 Workspace 聚合
- [x] 旧 SQLite 数据迁移到 default Workspace
- [x] 多租户安全隔离回归测试

## 阶段 4：Production Engineering ✅ Phase 4

### Evaluation 2.0

- [x] JSONL Dataset 与 Code Case 契约
- [x] 规则 Evaluator、工具轨迹评分与可选 LLM Judge（默认关闭）
- [x] Evaluation Runner、后台任务与 Workspace 隔离
- [x] 质量报告、工程指标、Cost / Reliability 聚合
- [x] Baseline vs Candidate 回归比较
- [x] 20 个真实 Benchmark Case
- [ ] Embedding / 向量检索与语义 Evaluator（后移）

### Observability

- [x] OpenTelemetry `http.request` / `agent.run` / `llm.call` / `tool.call` / `repository.query`
- [x] Prometheus 运行、LLM、Tool、Token、Timeout 指标
- [x] 敏感 Prompt / API Key 属性过滤
- [x] OTLP 导出配置与文档
- [ ] 审计防篡改与保留期策略（后移）

### Deployment / CI

- [x] 多阶段 Dockerfile、非 root 用户、健康检查
- [x] Docker Compose 与 `.agentos` volume
- [x] GitHub Actions ruff / pytest / docker build
- [ ] Kubernetes / 多副本部署（非目标）

### Reliability / Performance

- [x] SSE cancellation 传播到 LLM 与 Tool
- [x] 统一 Tool timeout，错误回填而非崩溃
- [x] parallel-safe Tool 并发，副作用 Tool 严格顺序
- [x] 有界 TTL Web cache，错误与敏感响应不缓存
- [x] Long-Term Memory character / token context budget
- [x] 可选配置价格映射与 `estimated_cost`（无价格返回 null）
- [x] timeout / tool / LLM / max-iteration / cancelled reliability rates

## 持续事项

- [x] 补测试：核心路径覆盖
- [x] 补文档：README 与 docs/ 全套架构、平台、评估、部署与可靠性文档
- [ ] 依赖维护：及时跟进安全更新
- [ ] 每个版本更新 CHANGELOG 与版本号

## 阶段 5：Dashboard Frontend ✅ 初始版本

- [x] Vue 3 / Vite / TypeScript / Element Plus / ECharts 工程
- [x] Overview / Agents / Run History / Trace / Tools / Evaluation / Usage 页面
- [x] `VITE_DEMO_MODE=true` Mock 模式
- [x] 统一 `src/api` 封装，页面不直接拼 fetch
- [x] Run Trace 安全展示：隐藏系统 Prompt、API Key 与敏感 Memory
- [x] 前端 Dockerfile、Nginx 代理和 Compose 联调
- [x] 组件 / API / Router 测试与 `npm run build`
- [ ] 后续：截图资源、端到端浏览器测试、按需加载优化

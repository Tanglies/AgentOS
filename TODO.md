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
- [ ] Multi-Agent：多 Agent 协作与消息路由

## 阶段 2：平台能力

- [ ] Agent 持久化（注册表切换为数据库实现）
- [ ] 运行记录持久化与历史查询
- [ ] Tool 管理（注册、分类、权限绑定）
- [ ] 权限系统（身份认证、配额、工具访问控制）
- [ ] API 完善（分页、过滤、批量操作）
- [ ] 数据模型与迁移机制

## 阶段 3：工程能力

- [ ] Observability：指标与链路追踪
- [ ] Evaluation：评测集与自动评分
- [ ] 性能优化：并发、缓存（流式响应已完成，见阶段 1）
- [ ] Docker 部署：镜像与本地一键启动
- [ ] CI 流水线（需确认后接入）

## 持续事项

- [x] 补测试：核心路径覆盖
- [x] 补文档：README 与 docs/ 三份文档
- [ ] 依赖维护：及时跟进安全更新
- [ ] 每个版本更新 CHANGELOG 与版本号
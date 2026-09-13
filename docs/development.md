# 开发指南

## 环境准备

- Python >= 3.11（推荐 3.12 / 3.13）
- Git

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

依赖分为两组：运行时依赖在 `[project.dependencies]`，开发依赖（pytest / pytest-asyncio / ruff）在
`[project.optional-dependencies].dev`。新增运行时依赖需谨慎评估，避免引入重量级库。

## 常用命令

| 目的 | 命令 |
| --- | --- |
| 启动服务 | `.\.venv\Scripts\python.exe -m agentos serve --port 8000` |
| 开发模式（热重载） | `.\.venv\Scripts\python.exe -m agentos serve --reload` |
| 查看版本 | `.\.venv\Scripts\python.exe -m agentos version` |
| 运行测试 | `.\.venv\Scripts\python.exe -m pytest` |
| 静态检查 | `.\.venv\Scripts\python.exe -m ruff check .` |
| 自动修复 | `.\.venv\Scripts\python.exe -m ruff check . --fix` |

## 目录约定

```
src/agentos/
├── api/          # 只做协议转换与依赖装配，不写业务逻辑
│   ├── app.py        # create_app / lifespan / 异常处理
│   ├── middleware.py # 请求上下文与访问日志
│   ├── deps.py       # 依赖注入类型别名
│   ├── schemas.py    # 请求与响应模型
│   └── routes/       # 按资源拆分的路由模块
├── core/         # 与业务无关的配置、日志、上下文与异常
├── database/     # SQLite 连接、迁移、Repository 基座与持久化模型
├── repositories/ # Agent / Run / Tool 规范仓储入口
├── evaluation/   # Metrics / Collector / Report
├── llm/          # 模型访问层（含 ToolSpec / ToolCall 协议模型）
└── runtime/      # Agent 领域模型、服务层与执行内核
    └── services/ # Agent 生命周期与 Dashboard 读模型
    ├── tools.py         # Tool 抽象、ToolRegistry、参数校验与执行
    ├── memory.py        # 会话短期记忆（MemoryStore / SessionState）
    ├── long_term_memory.py # 长期记忆（SQLite + 关键词召回）
    ├── memory_tools.py  # remember / recall 工具
    ├── planning.py      # 运行期执行计划（contextvars 隔离）
    ├── plan_tools.py    # create_plan / update_plan_step 工具
    ├── agent_tools.py   # delegate_to_agent 多 Agent 委托
    ├── sandbox.py       # 工作区路径沙箱与敏感文件黑名单
    ├── local_tools.py   # 目录 / 文件 / 搜索 / 命令工具
    ├── web_tools.py     # 网页抓取（SSRF 防护）与联网搜索
    └── builtin_tools.py # 通用工具与默认注册表工厂
tests/            # 与 src 结构对应的测试文件
docs/             # 架构、配置与开发文档
```

新增代码时遵循以下约束：

- `api` 层不直接调用 `httpx` 或外部服务，统一经由 `runtime` / `llm`
- `llm` 层不感知 HTTP 概念（除自身协议实现），不引用 `fastapi`
- `core` 层不引用上层模块；新持久化代码从 `agentos.database` 导入，不要继续扩展旧路径
- `evaluation` 只依赖 `runtime.repositories` 的只读查询能力，不反向修改运行记录
- 每个公开函数与类都要有简洁文档字符串

## 测试规范

- 使用 `pytest` + `pytest-asyncio`（`asyncio_mode = "auto"`，异步测试无需装饰器）
- 外部模型调用统一使用 `httpx.MockTransport` 或自定义 `LLMClient` 替身，测试不依赖网络
- 工具执行通过自定义 `Tool` 替身验证，不依赖真实外部 API
- `conftest.py` 中的 `clean_agentos_env` 会自动清理宿主环境变量，保证用例只依赖代码默认值
- 新增能力时至少覆盖：正常路径、边界条件、错误映射

当前覆盖范围：

| 测试文件 | 覆盖内容 |
| --- | --- |
| `tests/test_config.py` | 默认值、环境变量覆盖、密钥脱敏、非法配置拒绝、缓存 |
| `tests/test_logging.py` | JSON / console 格式、上下文注入、脱敏、幂等配置 |
| `tests/test_llm_clients.py` | echo 行为、工厂解析、请求构造、重试、错误与超时映射、tools / tool_calls 编解码 |
| `tests/test_tools.py` | 工具声明、JSON Schema 子集校验、注册表、执行与错误回填、内置工具 |
| `tests/test_local_tools.py` | 路径沙箱、敏感文件拦截、目录/文件/搜索/写入、命令开关与超时 |
| `tests/test_memory.py` | 会话存储、LRU 淘汰、轮次对齐截断、Runtime 集成与会话 API |
| `tests/test_web_tools.py` | SSRF 防护、重定向重新校验、HTML 转文本、抓取与搜索 |
| `tests/test_long_term_memory.py` | 持久化跨实例、关键词召回、记忆工具、自动召回注入与 API |
| `tests/test_streaming.py` | SSE 解析、tool_calls 分片聚合、事件流顺序、SSE 端点 |
| `tests/test_planning.py` | 计划模型、计划工具、运行期隔离、系统提示词注入与 API |
| `tests/test_multi_agent.py` | 委托工具、动态 Agent 列表、深度限制、子 Agent 隔离与 API |
| `tests/test_runtime.py` | 运行结果、历史消息、未知 Agent、空输入、迭代上限、注册表、多轮工具调用 |
| `tests/test_api.py` | 健康探针、请求 ID、Agent CRUD、运行接口、工具查询与统一错误响应 |
| `tests/test_auth.py` / `tests/test_api_keys.py` | API Key 认证、数据库密钥、权限边界、工具执行鉴权 |
| `tests/test_database.py` / `tests/test_database_package.py` / `tests/test_repository.py` | SQLite 连接、迁移账本、Repository 基座与兼容路径 |
| `tests/test_evaluation.py` / `tests/test_evaluation_package.py` | 指标计算、Metric 扩展、采集器与报告格式 |
| `tests/test_observability.py` / `tests/test_audit.py` | trace 上下文、审计记录与查询 |
| `tests/test_agent_repository.py` / `tests/test_agent_api.py` | Agent 结构化持久化、生命周期 API、权限与数据库恢复 |
| `tests/test_run_query_api.py` | Run 过滤、双分页、token_usage 与权限 |
| `tests/test_dashboard_api.py` | Overview、工具统计、错误列表、Dashboard 权限 |
| `tests/test_evaluation_api.py` | Evaluation 汇总、过滤、异常与权限 |
| `tests/test_eval_dataset.py` / `test_eval_rules.py` / `test_eval_runner.py` | JSONL、规则评分、工具轨迹、并发 Runner |
| `tests/test_llm_judge.py` / `test_eval_regression.py` | Judge 默认关闭、解析与 Baseline/Candidate |
| `tests/test_observability_tracing.py` / `test_observability_metrics.py` | OTel Span、敏感字段过滤、Prometheus 指标 |
| `tests/test_cancellation.py` / `test_tool_concurrency.py` | 取消传播、timeout 与串并行策略 |
| `tests/test_cache.py` / `test_memory_budget.py` / `test_cost.py` / `test_reliability_metrics.py` | Phase 4D 性能与成本回归 |
| `tests/test_docker_config.py` | Dockerfile、Compose 与 CI 结构检查 |

## 数据库迁移规范

新增表或字段时：

1. 修改对应 Repository schema，保证全新建库可以直接使用；
2. 为已存在数据库增加 `database/migrations/` 中的 `Migration(version, name, sql)`；
3. 运行 `tests/test_database_package.py` 验证迁移只执行一次；
4. 不要把破坏性迁移直接写进业务启动路径。

## 代码规范

- 行宽 100，规则集 `E F I UP B SIM`（见 `pyproject.toml` 的 `[tool.ruff]`）
- 类型标注尽量完整，公开接口必须标注
- 导入顺序：标准库 → 第三方 → 本项目（ruff 自动整理）
- 注释解释「为什么」，不复述「做了什么」

## 提交规范

使用 Conventional Commits：

```
feat: add agent memory retrieval module
fix: correct tool call timeout handling
docs: update architecture overview
refactor: simplify runtime message loop
test: cover llm retry backoff
```

提交前自检：

1. `.\.venv\Scripts\python.exe -m pytest` 全部通过
2. `.\.venv\Scripts\python.exe -m ruff check .` 无告警
3. 有 Docker 的环境执行 `docker build -t agentos:local .`；CI 会执行同一检查
3. 同步更新 `CHANGELOG.md`；核心功能变化同步更新 `README.md`

## 常见问题

**安装依赖很慢或超时**
本机可走代理：`$env:HTTPS_PROXY = "http://127.0.0.1:7897"` 后重试 pip / git 命令。

**端口被占用**
`agentos serve --port 8010` 指定其他端口，或设置 `AGENTOS_API__PORT`。

**配置没有生效**
环境变量优先级高于 `.env`；`.env` 只在进程启动目录查找。修改后需重启服务。

**测试报缺少依赖**
确认使用的是虚拟环境解释器：`.\.venv\Scripts\python.exe -m pytest`，而不是系统 Python。
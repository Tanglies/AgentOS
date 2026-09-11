# AGENTS.md

本文件由 Codex / AI 编码助手在仓库中工作时自动加载。桌面版、VS Code 扩展与 CLI 共用本文件，
因此任何界面打开 `E:\Agent` 都能立即获得项目上下文与工作约定。

## 项目概览

- **AgentOS**：企业级大模型 Agent 平台，目标能力为 Tool Calling、Memory、Evaluation、Observability
- **技术栈**：Python 3.11+ / FastAPI / Pydantic v2 / httpx / pytest / ruff
- **当前版本**：0.1.0（工程基座：服务可启动、Runtime 可运行、模型层可替换）
- 入口代码 `src/agentos`，测试 `tests`，文档 `docs`，迭代计划 `TODO.md`，变更记录 `CHANGELOG.md`

## 环境与常用命令

```powershell
# 安装（含开发依赖）
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 启动服务（默认端口 8000，文档 http://127.0.0.1:8000/docs）
.\.venv\Scripts\python.exe -m agentos serve --port 8000

# 运行测试 / 静态检查（提交前必须都通过）
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .

# 真实模型冒烟测试（消耗 token，按需运行）
.\.venv\Scripts\python.exe examples\qwen_smoke.py
```

VS Code 用户也可直接运行任务：`Ctrl+Shift+B`（启动服务）或 `Ctrl+Shift+P` → `Tasks: Run Task`。

## 配置与密钥（重要）

- 配置来自环境变量与 `.env`（`.env` 已被 gitignore，模板见 `.env.example`）
- **禁止提交**：`.env`、`*apiKey*.csv`、`*apikey*.csv`、`secrets/` 及任何密钥文件
- 当前模型：Qwen（OpenAI 兼容模式，`AGENTOS_LLM__BASE_URL` 必须使用 `/compatible-mode/v1` 端点，
  不是控制台 CSV 里的 `dashScope` 原生端点）
- 免费额度用尽时只需替换 `AGENTOS_LLM__MODEL`（备选：qwen3.8-flash / qwen3.7-plus / qwen3.6-plus）

## 代码约定

- 分层依赖严格单向：`api → runtime → llm`，`core` 横切复用，**禁止反向依赖**
- 新增模型服务：实现 `LLMClient` 并 `register_provider`，不要改动调用方
- 新增能力必须附带测试；每个公开类/函数要有简洁文档字符串
- 行宽 100，规则集 `E F I UP B SIM`（见 `pyproject.toml`）
- 提交信息使用 Conventional Commits（`feat` / `fix` / `docs` / `refactor` / `test` / `chore`），英文主体

## 迭代流程

1. 检查工作区与最近提交，确认基线健康（跑一遍测试）
2. 从 `TODO.md` 选择一个「小而完整、当天可验证」的任务，只做一件
3. 实现 + 测试 + 更新 `CHANGELOG.md`（核心功能同步更新 `README.md`）
4. 提交并推送 `main`；涉及数据库结构重大变化 / 架构调整 / 大量删除时改开 PR，不自动合并

## 红线

- 禁止修改或删除：`.env`、`secrets/`、密钥文件、`.github/workflows`、生产环境配置、用户数据目录
- 禁止：删除已有核心功能、擅自修改项目方向、引入未经确认的大型依赖、自动合并高风险 PR
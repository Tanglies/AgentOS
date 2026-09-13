# Deployment

## 本地运行

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m agentos serve --host 127.0.0.1 --port 8000
```

生产环境不要使用 reload，也不要把 `.env` 或真实密钥打进镜像。使用进程管理器
（systemd、Windows Service、容器编排器）负责重启和日志采集。

## Docker 镜像

`Dockerfile` 使用 Python 3.11 slim 多阶段构建：

- builder 阶段安装依赖到独立虚拟环境；
- runtime 阶段只复制虚拟环境与 `src/`；
- 使用非 root 用户 `agentos`；
- 暴露 `/app/.agentos` 作为持久化卷；
- `HEALTHCHECK` 调用 `/health/ready`；
- 默认不复制 `.env`、`.agentos`、`.venv`。

构建与运行：

```powershell
docker build -t agentos:local .
docker run --rm -p 8000:8000 `
  -v agentos-data:/app/.agentos `
  -e AGENTOS_LLM__PROVIDER=echo `
  agentos:local
```

## Compose

```powershell
docker compose up --build
curl.exe http://127.0.0.1:8000/health/ready
```

`docker-compose.yml` 默认：

- 持久化命名卷 `agentos-data` 到 `/app/.agentos`；
- `AGENTOS_TOOLS__ALLOW_SHELL=false`；
- `AGENTOS_OBSERVABILITY__PROMETHEUS_ENABLED=true`；
- 服务重启策略与健康检查。

生产环境应通过 secret manager 注入 `AGENTOS_LLM__API_KEY`，不要写入 Compose
文件或镜像层。

## 健康检查

| 路径 | 用途 |
| --- | --- |
| `/health` | liveness，进程存活与版本 |
| `/health/ready` | readiness，运行时与 LLM 配置已初始化 |

容器编排器应在 readiness 通过后再接流量。SQLite 卷不可写时不要继续启动服务。

## 配置

常见环境变量：

```text
AGENTOS_ENVIRONMENT=production
AGENTOS_LLM__PROVIDER=openai_compatible
AGENTOS_LLM__BASE_URL=https://provider.example/v1
AGENTOS_LLM__API_KEY=...
AGENTOS_LLM__MODEL=...
AGENTOS_AUTH__ENABLED=true
AGENTOS_AUTH__API_KEYS=["bootstrap-secret"]
AGENTOS_RUNS__DB_PATH=/app/.agentos/runs.db
AGENTOS_MEMORY__LONG_TERM_DB_PATH=/app/.agentos/memory.db
AGENTOS_EVALUATION__DB_PATH=/app/.agentos/evaluations.db
```

完整列表见 [配置说明](configuration.md)。当前认证仍是平台 API Key，不是终端用户
账号密码体系；多用户部署需要结合后续登录系统或外部身份代理。

## CI

`.github/workflows/ci.yml` 在 Python 3.11 上执行：

1. 安装项目与开发依赖；
2. `ruff check .`；
3. `pytest`；
4. `docker build`。

CI 使用 echo provider，不配置真实收费密钥，也不访问真实模型。任何一步失败都会
让 workflow 失败。

## 上线检查清单

- [ ] `ruff check .` 全通过
- [ ] `pytest` 全通过
- [ ] `docker build` 成功
- [ ] `/health/ready` 返回 200
- [ ] SQLite volume 有持久化权限
- [ ] `AGENTOS_TOOLS__ALLOW_SHELL=false`
- [ ] API Key 或外部认证已启用
- [ ] LLM Key 由 secret manager 注入
- [ ] OTLP/Prometheus 端点按环境启用
- [ ] 已确认预算、价格映射与配额上限

## 当前限制

本机 Windows 环境未安装 Docker，Phase 4 只能做 Dockerfile/Compose/CI 的结构测试；
镜像构建结果以 CI 的 `docker build` 为准。SQLite 适合单实例和轻量部署，多实例
需要外部数据库与共享存储，后移到后续阶段。
## Frontend Dashboard

`docker compose up --build` will start both services:

- `agentos`: FastAPI backend on port 8000
- `frontend`: Nginx + Vue Dashboard on port 5173

Nginx proxies `/api` and `/health` to `agentos:8000`. The frontend image defaults to `VITE_DEMO_MODE=true`, so GitHub visitors can explore the dashboard without a real LLM. Change the Compose build arg to `"false"` to use live backend data.

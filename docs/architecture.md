# 架构设计

## 分层与依赖方向

```
┌─────────────────────────────────────────────┐
│ api       FastAPI 装配 / 中间件 / 路由 / DTO │
├─────────────────────────────────────────────┤
│ runtime   Agent / Message / AgentRuntime     │
├─────────────────────────────────────────────┤
│ llm       LLMClient 抽象 / 具体实现 / 工厂    │
├─────────────────────────────────────────────┤
│ core      配置 / 日志 / 上下文 / 异常         │
└─────────────────────────────────────────────┘
```

依赖方向严格自上而下：`api → runtime → llm`，`core` 作为横切基础被各层复用。
反向依赖（如 `core` 引用 `api`）被禁止，保证底层可独立测试与替换。

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
| 内置工具 | `runtime/builtin_tools.py` | `get_current_time` / `calculate` 两个零依赖示例工具 |
| 运行内核 | `runtime/runtime.py` | 迭代调用模型、统计用量、产出 `RunResult` |
| LLM 契约 | `llm/base.py` | `LLMMessage` / `LLMResponse` / `LLMClient` |
| LLM 实现 | `llm/echo.py`, `llm/openai_compatible.py` | 回显客户端与 OpenAI 兼容 HTTP 客户端 |
| LLM 工厂 | `llm/factory.py` | provider 注册表与实例化 |
| 应用装配 | `api/app.py` | lifespan 建资源、挂载中间件、路由与异常处理 |

## 一次运行的调用链

```
Client
  │  POST /api/v1/runs
  ▼
RequestContextMiddleware        生成 request_id，写入 X-Request-ID
  ▼
runs.create_run                 解析请求，选择 Agent
  ▼
AgentRuntime.run                组装消息，绑定 run_id
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

## 扩展点

- **新增模型服务**：实现 `LLMClient` → `register_provider("name", factory)` → 配置 `AGENTOS_LLM__PROVIDER=name`
- **新增工具**：继承 `Tool` 声明 `name` / `description` / `parameters` → 注册进 `ToolRegistry` → 在 `Agent.tools` 中引用
- **工具调用链路**：`AgentRuntime._should_continue` 检测 `tool_calls` → `ToolRegistry.execute` 校验并执行 → 结果回填后再次调用模型
- **持久化 Agent**：`AgentRegistry` 接口保持不变，替换为数据库实现即可
- **新增路由**：在 `api/routes/` 下新增模块，并在 `api/app.py` 挂载
- **外部日志采集**：`AGENTOS_LOGGING__FORMAT=json` 输出 JSON 行，直接被 Fluent Bit / Loki 等采集

## v0.1 边界

当前版本是工程基座，**已实现 Tool Calling**。**尚未实现**：Memory、Multi-Agent、鉴权与配额、
持久化存储、评测体系、指标与链路追踪、容器化部署。这些能力按 `TODO.md` 的阶段推进，接入时保持既有分层与接口不变。
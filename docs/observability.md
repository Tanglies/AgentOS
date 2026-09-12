# 可观测性

## 上下文

一次调用的完整链路靠六个上下文字段串起来。它们存放在 `contextvars` 里，
异步链路中自动传递，日志系统会读取并附加到每条日志上。

| 字段 | 含义 | 谁写入 | 示例 |
| --- | --- | --- | --- |
| `trace_id` | 一次完整调用链 | 请求中间件生成或透传 | `trace_29f4f7f9a7a74b75` |
| `request_id` | 单次 HTTP 请求 | 请求中间件 | `req_4a1b...` |
| `run_id` | 一次 Agent 运行 | `AgentRuntime` | `run_be04a637...` |
| `agent_name` | 当前 Agent | `AgentRuntime` | `assistant` |
| `tool_name` | 正在执行的工具 | `ToolRegistry` | `calculate` |
| `actor` | 调用方密钥指纹 | 认证中间件 | `0f3a9c2b71d4` |

### 链路串联

```text
HTTP 请求
  │  middleware 生成 trace_id / request_id
  ▼
Runtime
  │  bind(run_id, agent_name)
  ▼
LLM 调用
  │
  ▼
Tool 执行
  │  bind(tool_name)
  ▼
Repository / Database
```

每一层打出的日志都会带上当前已绑定的全部字段。例如工具执行的日志：

```text
tool executed | trace_id=trace_29f4... request_id=req_4a1b... run_id=run_be04...
                agent_name=assistant tool_name=calculate tool=calculate call_id=c1
```

这样一次请求里"调了哪些工具、每个工具花了多久、哪个失败了"都能靠 `trace_id` 过滤出来。

### 客户端如何参与

请求头 `X-Trace-ID` 会被透传，响应头也会回显：

```powershell
# 客户端指定 trace，便于和上游系统对齐
curl.exe http://127.0.0.1:8000/api/v1/agents -H "X-Trace-ID: trace_from_gateway"
```

不传时服务端自动生成 `trace_` 前缀的 ID。

### 在代码里绑定

```python
from agentos.core.context import bind

with bind(run_id="run_x", agent_name="assistant"):
    ...  # 这段代码里打的所有日志都会带上这两个字段
```

字段名写错会直接抛 `ValueError` —— 静默忽略拼写错误会让排查变得很痛苦。

## 审计日志

### 与普通日志的区别

| | 普通日志 | 审计日志 |
| --- | --- | --- |
| 读者 | 开发者 | 合规与追责 |
| 内容 | 任意调试信息 | 固定的四要素 |
| 去向 | stdout，会被采集系统滚动 | SQLite，持久可查 |
| 量级 | 大 | 小（只记关键动作） |

### 四要素

审计记录固定回答四个问题：

- **谁** `actor` —— API Key 指纹；认证关闭时为 `None`（匿名）
- **什么时候** `created_at`
- **对什么做了什么** `action` + `target`
- **结果如何** `status`（`success` / `failure`）

其余字段（`trace_id` / `run_id` / `agent_name` / `tool_name`）用于把记录挂回完整调用链。

### 记录的动作

| action | 触发时机 | target |
| --- | --- | --- |
| `agent.run` | 每次 Agent 运行结束（成功与失败都记） | Agent 名称 |
| `tool.execute` | 每次工具执行（成功与失败都记） | 工具名称 |
| `agent.register` | 注册 Agent | Agent 名称 |
| `agent.unregister` | 注销 Agent | Agent 名称 |

### 上下文自动捕获

调用方**只需说明做了什么**，上下文字段自动带上：

```python
audit.record(ACTION_TOOL_EXECUTE, target="calculate", detail="1+1=2")
```

`actor` / `trace_id` / `run_id` / `agent_name` / `tool_name` 全部从 `contextvars` 读取。
少传一个字段就少一个漏记的理由。

### 查询

```powershell
# 最近 50 条
curl.exe http://127.0.0.1:8000/api/v1/audit

# 某次运行的全部动作
curl.exe "http://127.0.0.1:8000/api/v1/audit?run_id=run_be04a637bcea48c1"

# 某个密钥做过的操作
curl.exe "http://127.0.0.1:8000/api/v1/audit?actor=0f3a9c2b71d4"

# 只看失败的
curl.exe "http://127.0.0.1:8000/api/v1/audit?status=failure"

# 最早在前
curl.exe "http://127.0.0.1:8000/api/v1/audit?order=asc"
```

### 密钥指纹

审计记录的是密钥的 **SHA-256 前 12 位**，不是密钥本身：

```python
def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
```

用途是区分"哪把钥匙"，且**不可反推原文**。认证关闭时 `actor` 为空，表示匿名。

## 配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTOS_AUDIT__ENABLED` | `true` | 是否记录审计 |
| `AGENTOS_AUDIT__DB_PATH` | `.agentos/audit.db` | SQLite 文件路径 |
| `AGENTOS_AUDIT__MAX_RECORDS` | `20000` | 保留最近 N 条，超出淘汰最旧的 |

审计与运行记录**分开存储**：运行记录面向排查（量大、含完整消息轨迹），
审计面向追责（量小、字段固定、需要长期保留）。

## 已知边界

- **审计写入是同步的** —— 与现有 SQLite 访问方式一致，单条写入 < 1ms，对本地平台可接受
- **没有防篡改** —— 记录可被直接修改；需要强合规时应写入独立的追加式存储
- **没有保留期策略** —— 目前只按条数淘汰，没有按时间的 TTL
# Tool Permissions

## 两层模型

Tool 权限分为可见性和执行权限：

```text
系统代码注册工具
  ↓
Workspace Tool Policy
  ↓
Agent Tool Policy
  ↓
API Key / User Permission
  ↓
暴露给 LLM 的 ToolSpec

执行 ToolCall
  ↓
再次检查 Workspace / Agent Policy
  ↓
再次检查 tool:execute
```

没有权限的工具不会出现在模型中；即使模型伪造 ToolCall，执行点也会拒绝。

## 风险等级

| 等级 | 默认行为 | 示例 |
| --- | --- | --- |
| `low` | 默认可用 | `calculate`、`get_current_time` |
| `medium` | 默认可用，可按 Workspace 禁用 | `fetch_url`、`write_file` |
| `high` | 默认禁用，必须显式启用 | `run_command` |

`run_command` 仍保持默认不注册/不启用；配置可注册不代表 Workspace 自动授权。

## Tool 元数据

平台数据库保存：

- `tools`：代码注册工具的元数据；
- `workspace_tools`：Workspace 级启用/禁用；
- `agent_tools`：Agent 级启用/禁用。

HTTP 只能管理可信工具的配置和授权，**不能上传任意 Python Tool 代码**。

## API

```text
GET    /api/v1/tools
PATCH  /api/v1/tools/{name}
GET    /api/v1/agents/{name}/tools
PATCH  /api/v1/agents/{name}/tools/{tool_name}
```

示例：

```powershell
curl.exe -X PATCH http://127.0.0.1:8000/api/v1/tools/calculate `
  -H "X-API-Key: sk-agentos-..." `
  -H "Content-Type: application/json" `
  -d '{"enabled": false}'
```

## 权限

- `tool:read`：查看 Workspace 可见工具；
- `tool:execute`：执行工具；
- `tool:admin`：修改 Workspace / Agent 工具策略。

工具执行失败会回填为 `is_error` 结果，不会绕过权限或直接执行。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tool_management.py tests/test_tool_permissions.py -q
```

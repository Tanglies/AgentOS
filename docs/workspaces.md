# Workspaces and Membership

## Workspace API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/workspaces` | 创建 Workspace，当前用户成为 owner |
| GET | `/api/v1/workspaces` | 列出当前用户所属 Workspace |
| GET | `/api/v1/workspaces/{id}` | 获取 Workspace |
| PATCH | `/api/v1/workspaces/{id}` | 更新名称，需要 owner/admin |
| DELETE | `/api/v1/workspaces/{id}` | 删除，仅 owner，default Workspace 不可删 |
| GET | `/api/v1/workspaces/{id}/members` | 成员列表 |
| POST | `/api/v1/workspaces/{id}/members` | 添加成员 |
| DELETE | `/api/v1/workspaces/{id}/members/{user_id}` | 移除成员 |

创建示例：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/workspaces `
  -H "X-API-Key: sk-bootstrap-admin" `
  -H "Content-Type: application/json" `
  -d '{"name":"Research Team"}'
```

## User API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/users` | 创建用户 |
| GET | `/api/v1/users` | 用户列表 |
| GET | `/api/v1/users/{id}` | 用户详情 |

用户接口使用 `user:read` / `user:write` 权限。

## 角色

| 角色 | 能力 |
| --- | --- |
| `owner` | 全部 Workspace 操作，可删除 Workspace |
| `admin` | 可更新 Workspace、管理成员 |
| `member` | 使用 Workspace 资源 |
| `viewer` | 只读访问 Workspace 资源 |

## API Key 与 Workspace

API Key 数据库记录包含 `user_id` 和 `workspace_id`。请求认证成功后，
当前身份决定所有资源 scope。

静态 bootstrap API Key 映射到：

```text
user_id = 1
workspace_id = 1
```

静态管理员可以显式签发指定 user/workspace 的数据库密钥，用于引导新 Workspace；
普通数据库密钥只能在自身 user/workspace 内使用。

## Deletion

default Workspace 禁止删除。删除自定义 Workspace 时，平台先清理成员关系；
跨数据库资源的级联清理策略会在部署层和后续版本继续补强，当前优先保证
删除后的 Workspace 不再作为可认证的租户入口。

# Workspaces and Membership

## Workspace API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/workspaces` | 创建 Workspace，当前用户成为 owner |
| GET | `/api/v1/workspaces` | 列出当前用户所属 Workspace |
| GET | `/api/v1/workspaces/{id}` | 获取 Workspace |
| PATCH | `/api/v1/workspaces/{id}` | 更新名称，需要 owner/admin |
| DELETE | `/api/v1/workspaces/{id}` | 删除，仅 owner，default Workspace 不可删 |
| GET | `/api/v1/workspaces/{id}/members` | 成员列表，支持页码与稳定游标分页 |
| POST | `/api/v1/workspaces/{id}/members` | 添加成员 |
| PATCH | `/api/v1/workspaces/{id}/members/batch` | 原子批量更新成员角色 |
| PATCH | `/api/v1/workspaces/{id}/members/{user_id}` | 更新成员角色 |
| DELETE | `/api/v1/workspaces/{id}/members/batch` | 原子批量移除成员 |
| DELETE | `/api/v1/workspaces/{id}/members/{user_id}` | 移除成员；普通成员可退出自己 |

Workspace 目录保留 `page` / `page_size` 页码分页，同时在响应中返回
`next_cursor`。游标按 Workspace 自增 `id` 升序定位，默认每页最多 100 条；
翻页期间新增 Workspace 不会让后续页面重复或偏移：

```http
GET /api/v1/workspaces?page_size=100
GET /api/v1/workspaces?page_size=100&cursor=eyJ2IjoyLCJrZXkiOiI0MiJ9
```

`cursor` 不能与 `page` 同时使用；损坏游标、跨列表游标或排序方向不一致的游标
返回 `422 validation_error`。`total` 表示当前用户可见的 Workspace 总数。

Workspace 成员目录同样保留 `page` / `page_size`，并按成员 `user_id` 升序返回
稳定 `next_cursor`。遍历期间新增成员不会让后续页面重复或偏移，默认每页最多
100 条，`total` 表示该 Workspace 的成员总数：

```http
GET /api/v1/workspaces/42/members?page_size=100
GET /api/v1/workspaces/42/members?page_size=100&cursor=eyJ2IjoyLCJrZXkiOiI0MiJ9
```

owner/admin 可将非 owner 成员调整为 `admin`、`member` 或 `viewer`，角色变更会写入
`workspace.member.update` 审计事件。owner 角色不能通过成员接口变更或重新分配：

```powershell
curl.exe -X PATCH http://127.0.0.1:8000/api/v1/workspaces/42/members/7 `
  -H "X-API-Key: sk-bootstrap-admin" `
  -H "Content-Type: application/json" `
  -d '{"role":"viewer"}'
```

同一规则适用于批量接口：单次最多提交 100 个唯一 `user_id`，所有角色写入在同一
SQLite 事务中完成。只要批次包含 owner 目标，整批请求都会在写入前返回 `403`；
不存在或不属于目标 Workspace 的成员通过 `missing_user_ids` 报告，不影响其他
合法成员的更新。实际角色变化逐项写入 `workspace.member.update` 审计：

```powershell
curl.exe -X PATCH http://127.0.0.1:8000/api/v1/workspaces/42/members/batch `
  -H "X-API-Key: sk-bootstrap-admin" `
  -H "Content-Type: application/json" `
  -d '{"updates":[{"user_id":7,"role":"viewer"},{"user_id":8,"role":"admin"}]}'
```

批量移除与角色更新共享相同的权限和原子性边界。单次最多提交 100 个唯一
`user_id`；只要批次包含 owner，整批请求都会在写入前返回 `403`。不存在或
不属于目标 Workspace 的成员通过 `missing_user_ids` 报告，实际移除的成员逐项
写入 `workspace.member.remove` 审计事件：

```powershell
curl.exe -X DELETE http://127.0.0.1:8000/api/v1/workspaces/42/members/batch `
  -H "X-API-Key: sk-bootstrap-admin" `
  -H "Content-Type: application/json" `
  -d '{"user_ids":[7,8,9]}'
```

任何非 owner 成员都可以调用单条移除接口删除自己的成员关系，无需 admin 角色；
实际退出写入 `workspace.member.remove` 审计事件。成员不能借此删除其他用户，
owner 也不能退出 Workspace，调用后返回 `403 permission_denied`：

```powershell
curl.exe -X DELETE http://127.0.0.1:8000/api/v1/workspaces/42/members/7 `
  -H "X-API-Key: sk-member-key"
```

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

用户列表保留 `page` / `page_size` 页码分页，同时在响应中返回 `next_cursor`。
游标按数据库自增 `id` 升序定位，翻页期间新增用户不会让已读页面重复或偏移：

```http
GET /api/v1/users?page_size=100
GET /api/v1/users?page_size=100&cursor=eyJ2IjoyLCJrZXkiOiI0MiJ9
```

`cursor` 不能与 `page` 同时使用；损坏游标、跨列表游标或排序方向不一致的游标
返回 `422 validation_error`。`total` 始终表示当前用户总数，不是本页条数。

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

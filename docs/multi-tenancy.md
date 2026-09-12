# Multi-Tenant Agent Platform

## 目标

Phase 3 把 AgentOS 从单用户平台升级为支持用户、Workspace、资源隔离、Tool 策略、
配额和限流的多租户平台。

核心原则：

- 用户通过 Workspace 访问资源；
- 所有资源查询默认带 `workspace_id`；
- 隔离下沉到 Service / Repository，不依赖 route 手工过滤；
- 旧数据自动迁移到 default Workspace；
- 不删除已有数据库或公共 API。

## 模型

```text
User
  ↓ membership(role)
Workspace
  ↓
Agent / Run / Memory / API Key / Audit / Tool Policy / Quota
  ↓
Repository
  ↓
SQLite
```

### User

| 字段 | 含义 |
| --- | --- |
| `id` | 用户 ID |
| `username` | 唯一登录名 |
| `display_name` | 展示名称 |
| `status` | `active` / `disabled` |
| `created_at` / `updated_at` | 生命周期时间 |

### Workspace

| 字段 | 含义 |
| --- | --- |
| `id` | Workspace ID |
| `name` | 唯一名称 |
| `owner_id` | 所有者用户 |
| `created_at` / `updated_at` | 生命周期时间 |

### Membership

| 字段 | 含义 |
| --- | --- |
| `workspace_id` | Workspace |
| `user_id` | 用户 |
| `role` | `owner` / `admin` / `member` / `viewer` |
| `created_at` | 加入时间 |

## 请求上下文

认证成功后，以下字段进入 `contextvars`：

```text
actor
user_id
workspace_id
```

日志与审计自动包含：

```text
trace_id request_id workspace_id user_id run_id agent_name tool_name
```

API Key 明文、密码和敏感 token 不进入上下文，也不会写入日志。

## 资源隔离

| 资源 | 隔离键 |
| --- | --- |
| Agent | `workspace_id + name` 唯一 |
| Run | `workspace_id`，并记录 `user_id` |
| Memory | `workspace_id`，支持 `user` / `workspace` scope |
| API Key | `workspace_id` + `user_id` |
| Audit | `workspace_id` + `user_id` |
| Tool Policy | `workspace_id`，可增加到 Agent 级 |
| Quota | `workspace_id` |

跨 Workspace 访问优先返回 `404 not_found`，避免通过 `403` 泄露资源是否存在。

## 旧数据库迁移

旧 Agent / Run / Memory / API Key / Audit 表缺少 `workspace_id` 时，
Repository 初始化阶段会自动补列，并把旧记录归入：

```text
workspace_id = 1
user_id = 1
```

Agent 表会重建为：

```text
UNIQUE(workspace_id, name)
```

因此同名 Agent 可以在不同 Workspace 中共存。

## 兼容性

- 原有单用户调用默认使用 default Workspace；
- 原有 `unregister`、`run_store`、`long_term_memory` 等 API 保留；
- 旧数据库无需手工 SQL；
- 新响应只增加字段，不删除已有字段。

## 安全回归场景

- A 用户看不到 B Workspace；
- A 用户不能执行 B Agent；
- A 用户不能读取或删除 B Memory/Run；
- 无权限 Tool 不进入 ToolSpec；
- 伪造 ToolCall 也会在执行点失败；
- Quota 超额返回 429；
- Rate Limit 超额返回 429。

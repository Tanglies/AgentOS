# 数据库与 Repository

## 目标

AgentOS 的 SQLite 数据层负责四件事：

1. 连接与目录生命周期管理；
2. 表结构初始化和版本化迁移；
3. 把 SQL 与领域对象转换集中在 Repository；
4. 为删除、重建和兼容旧导入路径提供稳定行为。

新代码统一从 `agentos.database` 导入：

```python
from agentos.database import DatabaseManager, Migration, Repository
```

旧路径 `agentos.core.database.Database` 仍然可用，但只是兼容入口。

## 连接管理

`DatabaseManager` 是 `Database` 的语义化名称，二者行为一致。每次操作打开一个短连接，
退出时提交或回滚并显式关闭连接；不使用全局长连接，避免 SQLite 多线程限制和句柄泄漏。

连接时会做以下事情：

- 确保数据库文件的父目录存在；
- 如果数据库文件是新建的，执行当前 schema；
- 确保 `schema_migrations` 表存在；
- 按版本顺序应用尚未执行的迁移。

因此运行时手工删除 `.agentos/` 目录或单个 `.db` 文件后，下一次操作会自动恢复外层目录和
基础表结构。已经写入的数据不会恢复，但服务不会因为 `no such table` 直接进入 500。

## 迁移

迁移由 `database/migrations/base.py` 的 `Migration` 描述，由
`database/migrations/manager.py` 的 `MigrationRunner` 或 `DatabaseManager(migrations=...)`
执行。每个迁移包含：

| 字段 | 含义 |
| --- | --- |
| `version` | 单调递增的整数版本 |
| `name` | 便于排查的迁移名称 |
| `sql` | 一条或多条 SQLite DDL/DML |

`schema_migrations` 记录已执行版本。重复启动、并发创建连接或重启进程时，
已执行迁移不会再次执行。迁移 SQL 应当保持幂等或只执行一次的前向变更。

示例：

```python
from agentos.database import DatabaseManager, Migration

db = DatabaseManager(
    ".agentos/example.db",
    migrations=[
        Migration(1, "create-items", "CREATE TABLE items (id INTEGER PRIMARY KEY);"),
        Migration(2, "add-display-name", "ALTER TABLE items ADD COLUMN name TEXT;"),
    ],
)
```

## Repository 分层

| 层 | 路径 | 职责 |
| --- | --- | --- |
| 连接 | `database/connection.py` | 连接、建表、迁移账本 |
| 基座 | `database/repository.py` | `Repository`、参数化 `build_filter` |
| 持久化模型 | `database/models.py` | `SchemaMigration`、`Pagination` |
| 业务仓储 | `runtime/repositories.py` | Agent / Run / Memory / Audit / API Key 的 SQL 与行转换 |

业务仓储不直接在 Store 里拼 SQL。`RunStore`、`LongTermMemory`、`SQLiteAgentRegistry` 等
只保留业务语义，例如重名冲突、容量淘汰、检索词提取和运行状态转换。

## 兼容别名与命名

现有方法保持不变，同时提供更明确的仓储命名：

| 语义 | 现有方法 | 对齐方法 |
| --- | --- | --- |
| 创建运行 | `RunRepository.add` | `create_run` |
| 保存最终运行 | `RunRepository.add` | `finish_run` |
| 保存记忆 | `MemoryRepository.add` | `save_memory` |
| 搜索记忆 | `MemoryRepository.search` | `search_memory` |

这样旧调用方和隐藏测试不需要迁移，新代码可以使用更接近领域语义的名称。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_database.py tests/test_database_package.py tests/test_repository.py -q
.\.venv\Scripts\python.exe -m ruff check src/agentos/database src/agentos/runtime/repositories.py
```

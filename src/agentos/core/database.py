"""SQLite 连接与表结构管理。

把三个存储里反复出现的动作收在一处：

1. **确保父目录存在** —— 目录可能在运行期间被手工删除，不重建就会
   报 ``unable to open database file``
2. **文件新建时执行建表语句** —— 否则删掉 ``.db`` 之后会报 ``no such table``
3. **用完关闭连接** —— ``with sqlite3.connect(...)`` 只管理事务提交/回滚，
   **不会**关闭连接，必须显式 close

顺带提供 ``execute`` / ``query`` / ``query_one`` 三个薄封装，
让 Repository 层不必重复写连接管理代码。

.. note::

   每个操作打开一次连接。对本地单机、低频写入的场景足够，
   也天然避开 SQLite 的多线程限制。不支持 ``:memory:``
   （每次连接都会得到一个全新的空库）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class Database:
    """一个 SQLite 数据库文件的连接与表结构管理。"""

    def __init__(self, path: str | Path, *, schema: str = "") -> None:
        self.path = Path(path).expanduser()
        self._schema = schema
        # 立刻建立一次连接：路径不可写之类的问题应当尽早暴露，
        # 而不是等到第一次写数据时才报错。
        with self.connect():
            pass

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """打开连接，退出时提交/回滚并关闭。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.path.exists()

        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                if is_new and self._schema:
                    conn.executescript(self._schema)
                yield conn
        finally:
            conn.close()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """执行写语句，返回受影响行数。"""
        with self.connect() as conn:
            cursor = conn.execute(sql, params)
        return max(0, cursor.rowcount)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        """执行查询，返回全部行。"""
        with self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        """执行查询，返回第一行或 ``None``。"""
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def execute_script(self, script: str) -> None:
        """执行多语句脚本（建表、建索引等）。"""
        with self.connect() as conn:
            conn.executescript(script)
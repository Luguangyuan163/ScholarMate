"""MySQL 集成测试：构建表结构并确认重复启动不会破坏已有表。

需要环境变量 ``SM_TEST_MYSQL_URL`` 指向一个测试库（不要指向正式库），未配置时跳过：

    $env:SM_TEST_MYSQL_URL = "mysql+aiomysql://scholarmate:pw@127.0.0.1:3306/scholarmate_test?charset=utf8mb4"
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect

from app.core.database import Database

MYSQL_TEST_URL = os.environ.get("SM_TEST_MYSQL_URL", "")

pytestmark = pytest.mark.skipif(
    not MYSQL_TEST_URL,
    reason="未配置 SM_TEST_MYSQL_URL，跳过 MySQL 集成测试",
)

EXPECTED_TABLES = {"conversations", "messages", "uploaded_pdfs", "search_cache"}


async def _table_names(db: Database) -> set[str]:
    async with db.engine.begin() as conn:
        return await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))


async def test_mysql_schema_is_created_and_stable_across_restarts():
    db = Database(MYSQL_TEST_URL)
    await db.create_all()
    first = await _table_names(db)
    assert first >= EXPECTED_TABLES, f"缺少表: {EXPECTED_TABLES - first}"

    await db.create_all()  # 模拟应用重启
    second = await _table_names(db)
    assert second == first, "重复启动后表结构发生了变化"
    await db.close()

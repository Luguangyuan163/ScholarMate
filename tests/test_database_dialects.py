"""数据层方言行为：SQLite 专用设置与旧表迁移都不能影响其他数据库。

背景：系统同时支持 SQLite（桌面交付）与 MySQL（开发/答辩演示，Navicat 可视化）。
两处容易出错的地方：SQLite 的 PRAGMA 监听器会注册到 MySQL 引擎上；启动迁移里的
``DROP TABLE IF EXISTS papers`` 会误删新版论文实体表。
"""

from __future__ import annotations

import sqlite3

from sqlalchemy import event

from app.core.database import Database, _enable_sqlite_pragmas

MYSQL_URL = "mysql+aiomysql://scholarmate:pw@127.0.0.1:3306/scholarmate"


def test_mysql_url_skips_sqlite_setup():
    db = Database(MYSQL_URL)
    assert db.engine.dialect.name == "mysql"
    assert not event.contains(db.engine.sync_engine, "connect", _enable_sqlite_pragmas)


def test_sqlite_url_keeps_sqlite_setup(tmp_path):
    db_path = tmp_path / "nested" / "app.db"
    db = Database(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    assert db.engine.dialect.name == "sqlite"
    assert db_path.parent.exists()
    assert event.contains(db.engine.sync_engine, "connect", _enable_sqlite_pragmas)


async def test_legacy_papers_table_is_removed(tmp_path):
    """旧库里的链接论文表（无 normalized_title 列）应当被清理。"""
    db_path = tmp_path / "legacy.db"
    raw = sqlite3.connect(db_path)
    raw.execute("CREATE TABLE papers (id INTEGER PRIMARY KEY, title TEXT, url TEXT)")
    raw.commit()
    raw.close()

    db = Database(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await db.create_all()
    await db.close()

    raw = sqlite3.connect(db_path)
    tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master")}
    raw.close()
    assert "papers" not in tables


async def test_paper_entity_table_survives_create_all(tmp_path):
    """新版论文实体表（含 normalized_title 列）不能被启动迁移删除。"""
    db_path = tmp_path / "entity.db"
    raw = sqlite3.connect(db_path)
    raw.execute(
        "CREATE TABLE papers (id INTEGER PRIMARY KEY, title TEXT, normalized_title TEXT)"
    )
    raw.execute("INSERT INTO papers (title, normalized_title) VALUES ('LoRA', 'lora')")
    raw.commit()
    raw.close()

    db = Database(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await db.create_all()
    await db.close()

    raw = sqlite3.connect(db_path)
    rows = list(raw.execute("SELECT title FROM papers"))
    raw.close()
    assert rows == [("LoRA",)]

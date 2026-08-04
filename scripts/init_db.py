"""初始化数据库表结构。"""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.core.database import Database


async def main() -> None:
    settings = Settings()
    settings.ensure_dirs()
    db = Database(settings.database_url)
    await db.create_all()
    await db.close()
    print(f"数据库初始化完成: {settings.database_url}")


if __name__ == "__main__":
    asyncio.run(main())

"""ScholarMate 桌面启动入口。

用法:
    python run.py               # 启动本地服务并打开桌面窗口
    SM_HEADLESS=1 python run.py # 无窗口模式（调试 / CI）
"""

from __future__ import annotations

import logging
import os
import time

from app.config import Settings
from app.desktop import bootstrap
from app.main import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    settings = Settings()
    app = create_app(settings)
    handle = bootstrap.start_server(app, host=settings.app_host, port=settings.app_port)
    print(f"ScholarMate 本地服务已启动: {handle.url}")

    if os.environ.get("SM_HEADLESS", "0") == "1":
        print("无窗口模式运行中，按 Ctrl+C 退出")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return 0

    from app.desktop.window import create_window

    try:
        create_window(handle.url, title=settings.app_title, size=settings.app_size)
    finally:
        bootstrap.stop_server(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

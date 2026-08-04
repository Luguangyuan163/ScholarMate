"""桌面壳测试：本地服务启动/停止与端口分配（不打开窗口）。"""

from __future__ import annotations

import httpx

from app.desktop import bootstrap
from app.main import create_app


def test_server_start_stop(app_settings):
    app = create_app(app_settings)
    handle = bootstrap.start_server(app, host="127.0.0.1", port=0)
    try:
        resp = httpx.get(f"{handle.url}/api/health", timeout=5)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
    finally:
        bootstrap.stop_server(handle)
    assert not handle.thread.is_alive()


def test_find_free_port():
    port = bootstrap.find_free_port()
    assert 0 < port < 65536

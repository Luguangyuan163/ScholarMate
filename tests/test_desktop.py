"""桌面壳测试：本地服务启动/停止与端口分配（不打开窗口）。"""

from __future__ import annotations

import builtins

import httpx

from app.desktop import bootstrap
from app.desktop.window import _parse_size, create_window
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


def test_parse_size():
    assert _parse_size("1280x800") == (1280, 800)
    assert _parse_size("800x600") == (800, 600)


def test_create_window_requires_pywebview(monkeypatch):
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "webview":
            raise ImportError("No module named 'webview'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    try:
        create_window("http://127.0.0.1:1")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "pywebview" in str(exc)


def test_create_window_launches_webview(monkeypatch):
    calls = {}

    class FakeWebview:
        @staticmethod
        def create_window(title, url, width=None, height=None):
            calls["create_window"] = (title, url, width, height)

        @staticmethod
        def start():
            calls["start"] = True

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "webview":
            return FakeWebview
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    create_window("http://127.0.0.1:1", title="ScholarMate", size="800x600")
    assert calls["create_window"] == ("ScholarMate", "http://127.0.0.1:1", 800, 600)
    assert calls["start"] is True


def test_stop_server_already_exited():
    class FakeServer:
        should_exit = True

    class FakeHandle:
        server = FakeServer()
        thread = None

    bootstrap.stop_server(FakeHandle())


def test_wait_until_ready_times_out(monkeypatch):
    import urllib.request

    def _raise_oserror(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_oserror)
    try:
        bootstrap._wait_until_ready("http://127.0.0.1:1", timeout=0.3)
        raise AssertionError("expected TimeoutError")
    except TimeoutError as exc:
        assert "未就绪" in str(exc)

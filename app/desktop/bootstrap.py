"""本地服务生命周期：启动 Uvicorn、健康检查、停止。"""

from __future__ import annotations

import socket
import threading
import time
import urllib.request
from dataclasses import dataclass

import uvicorn

READY_TIMEOUT_SECONDS = 10.0


@dataclass
class ServerHandle:
    thread: threading.Thread
    server: uvicorn.Server
    url: str


def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def start_server(
    app,
    host: str,
    port: int,
    timeout: float = READY_TIMEOUT_SECONDS,
) -> ServerHandle:
    if port == 0:
        port = find_free_port(host)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    url = f"http://{host}:{port}"
    _wait_until_ready(url, timeout)
    return ServerHandle(thread=thread, server=server, url=url)


def stop_server(handle: ServerHandle) -> None:
    if handle.server.should_exit:
        return
    handle.server.should_exit = True
    handle.thread.join(timeout=5.0)


def _wait_until_ready(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"本地服务 {url} 在 {timeout}s 内未就绪")

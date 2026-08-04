"""pywebview 桌面窗口（P5 接入，依赖按需导入）。"""

from __future__ import annotations


def create_window(url: str, title: str = "ScholarMate", size: str = "1280x800") -> None:
    """创建桌面窗口并阻塞至窗口关闭；必须在主线程调用。"""
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("未安装 pywebview，请执行 pip install pywebview") from exc

    width, height = _parse_size(size)
    webview.create_window(title, url, width=width, height=height)
    webview.start()


def _parse_size(size: str) -> tuple[int, int]:
    width, height = size.lower().split("x")
    return int(width), int(height)

"""带限速与重试的 JSON 客户端，供各来源适配器复用。

同一个来源的请求必须串行且保持最小间隔，否则容易被限流；不同来源之间由
调用方并发调度，互不影响。
"""

from __future__ import annotations

import asyncio
import time

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

USER_AGENT = "ScholarMate/0.1 (graduation project)"
DEFAULT_TIMEOUT_SECONDS = 30.0
TRANSIENT_STATUS = (429, 500, 502, 503)


def _is_transient(exc: BaseException) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in TRANSIENT_STATUS
    )


class ThrottledJsonClient:
    """最小间隔限速 + 临时故障重试的 JSON 客户端。"""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        min_interval: float = 0.2,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self._min_interval = min_interval
        self._last_request_at = 0.0
        self._lock = asyncio.Lock()

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def get_json(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        async with self._lock:
            await self._throttle()
            response = await self._client.get(url, params=params, headers=headers)
            response.raise_for_status()
        return response.json()

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()

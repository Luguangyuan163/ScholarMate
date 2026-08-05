"""SSE 事件序列化公共工具。"""

from __future__ import annotations

import json


def sse_event(event: dict) -> str:
    """将事件字典序列化为 SSE 帧（event: <type>\\ndata: <json>\\n\\n）。"""
    return (
        f"event: {event['type']}\n"
        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    )


def sse_response(events):
    """包装事件流为 StreamingResponse，带禁用缓冲头。"""
    from fastapi.responses import StreamingResponse

    async def event_stream():
        async for event in events:
            yield sse_event(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

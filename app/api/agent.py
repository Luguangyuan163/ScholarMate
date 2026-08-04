"""Agent 对话接口（P3）：ReAct 循环 + SSE 流式输出。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.agent.agent_loop import agent_loop
from app.agent.tools import build_tools
from app.schemas.agent import AgentChatRequest

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat")
async def agent_chat(request: Request, payload: AgentChatRequest) -> StreamingResponse:
    llm = request.app.state.llm_client
    tools = build_tools(
        arxiv=request.app.state.arxiv_service,
        s2=request.app.state.s2_service,
        openalex=request.app.state.openalex_service,
        embedding=request.app.state.embedding_service,
        vector_store=request.app.state.vector_store,
        translation=request.app.state.translation_service,
    )

    async def event_stream():
        async for event in agent_loop(
            payload.query, tools, llm, max_iter=payload.max_iterations
        ):
            yield (
                f"event: {event['type']}\n"
                f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

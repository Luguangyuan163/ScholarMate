"""Agent 对话接口（P3）：ReAct 循环 + SSE 流式输出。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.agent.agent_loop import agent_loop
from app.agent.tools import build_tools
from app.api.sse import sse_response
from app.schemas.agent import AgentChatRequest

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat")
async def agent_chat(request: Request, payload: AgentChatRequest) -> StreamingResponse:
    return sse_response(
        _agent_events(request, payload.query, payload.max_iterations)
    )


@router.get("/chat-stream")
async def agent_chat_stream(
    request: Request,
    query: str = Query(min_length=1, max_length=500),
    max_iterations: int = Query(default=6, ge=1, le=10),
):
    """EventSource 使用的 GET 流式端点。"""
    return sse_response(_agent_events(request, query, max_iterations))


async def _agent_events(request: Request, query: str, max_iterations: int):
    llm = request.app.state.llm_client
    tools = build_tools(
        arxiv=request.app.state.arxiv_service,
        s2=request.app.state.s2_service,
        openalex=request.app.state.openalex_service,
        embedding=request.app.state.embedding_service,
        vector_store=request.app.state.vector_store,
        translation=request.app.state.translation_service,
    )
    async for event in agent_loop(query, tools, llm, max_iter=max_iterations):
        yield event

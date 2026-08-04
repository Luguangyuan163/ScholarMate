"""Agent 对话接口（P3 接入 SSE 流式）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.agent import AgentChatRequest

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat")
async def agent_chat(payload: AgentChatRequest) -> JSONResponse:
    return JSONResponse(status_code=501, content={"detail": "Agent 对话将在 P3 实现"})

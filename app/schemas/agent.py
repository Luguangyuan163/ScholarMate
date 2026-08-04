"""Agent 对话接口的请求模型（P3 接入）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    max_iterations: int = Field(default=5, ge=1, le=10)

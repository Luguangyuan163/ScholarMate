"""会话接口的请求模型。"""

from __future__ import annotations

from pydantic import BaseModel


class CreateConversationRequest(BaseModel):
    title: str = "新会话"


class MessageRequest(BaseModel):
    role: str
    content: str

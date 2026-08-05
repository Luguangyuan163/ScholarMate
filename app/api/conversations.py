"""会话管理接口：创建/列表/消息/删除（工作台侧边栏）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.common import utcnow
from app.models.conversation import Conversation, Message
from app.schemas.conversation import CreateConversationRequest, MessageRequest

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _conversation_payload(row: Conversation, message_count: int) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "message_count": message_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
async def list_conversations(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    rows = (
        await session.execute(
            select(Conversation).order_by(Conversation.updated_at.desc())
        )
    ).scalars().all()
    payload = []
    for row in rows:
        count = (
            await session.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == row.id)
            )
        ).scalar_one()
        payload.append(_conversation_payload(row, count))
    return payload


@router.post("")
async def create_conversation(
    payload: CreateConversationRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    row = Conversation(title=payload.title.strip() or "新会话")
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _conversation_payload(row, 0)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    row = await session.get(Conversation, conversation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    return {
        "id": row.id,
        "title": row.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.post("/{conversation_id}/messages")
async def add_message(
    conversation_id: int,
    payload: MessageRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    row = await session.get(Conversation, conversation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    message = Message(
        conversation_id=conversation_id,
        role=payload.role,
        content=payload.content,
    )
    row.updated_at = utcnow()
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    row = await session.get(Conversation, conversation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    await session.delete(row)
    await session.commit()
    return {"deleted": conversation_id}

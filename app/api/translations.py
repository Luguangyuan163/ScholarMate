"""翻译记录接口：已保存的对照翻译版本（列表/详情/删除）。"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.translation_record import TranslationRecord

router = APIRouter(prefix="/api/translations", tags=["translations"])


def _summary(row: TranslationRecord) -> dict:
    return {
        "id": row.id,
        "pdf_id": row.pdf_id,
        "filename": row.filename,
        "target_lang": row.target_lang,
        "total": row.total,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
async def list_translations(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    rows = (
        await session.execute(
            select(TranslationRecord).order_by(TranslationRecord.created_at.desc())
        )
    ).scalars().all()
    return [_summary(row) for row in rows]


@router.get("/{record_id}")
async def get_translation(
    record_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    row = await session.get(TranslationRecord, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="翻译记录不存在")
    return {
        **_summary(row),
        "segments": json.loads(row.segments_json or "[]"),
    }


@router.delete("/{record_id}")
async def delete_translation(
    record_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    row = await session.get(TranslationRecord, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="翻译记录不存在")
    await session.delete(row)
    await session.commit()
    return {"deleted": record_id}

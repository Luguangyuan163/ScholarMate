"""翻译记录模型：保存已完成的对照翻译版本。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import utcnow


class TranslationRecord(Base):
    __tablename__ = "translation_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    pdf_id: Mapped[int] = mapped_column(
        ForeignKey("uploaded_pdfs.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    target_lang: Mapped[str] = mapped_column(String(16), default="zh")
    segments_json: Mapped[str] = mapped_column(Text, default="[]")
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

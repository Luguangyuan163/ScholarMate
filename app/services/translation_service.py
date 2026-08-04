"""LLM 分段翻译服务（P4 接入）。"""

from __future__ import annotations


class TranslationService:
    async def translate_paragraph(self, text: str, target_lang: str = "zh") -> str:
        raise NotImplementedError("翻译服务将在 P4 接入")

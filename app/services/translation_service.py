"""LLM 分段翻译服务（P3 先行实现，Agent 翻译工具依赖）。"""

from __future__ import annotations

from app.core.llm_client import BaseLLMClient


class TranslationService:
    def __init__(self, llm: BaseLLMClient) -> None:
        self._llm = llm

    async def translate_paragraph(self, text: str, target_lang: str = "zh") -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    f"你是学术翻译助手。将文本翻译为{target_lang}，"
                    "术语准确，只输出译文，不要解释。"
                ),
            },
            {"role": "user", "content": text},
        ]
        return (await self._llm.chat(messages)).strip()

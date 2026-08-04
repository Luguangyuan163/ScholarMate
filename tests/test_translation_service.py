"""翻译服务测试。"""

from __future__ import annotations

from app.services.translation_service import TranslationService


class FakeChatLLM:
    async def chat(self, messages, **kwargs):
        assert messages[0]["role"] == "system"
        return "译文：你好"


async def test_translate_paragraph():
    service = TranslationService(llm=FakeChatLLM())
    result = await service.translate_paragraph("Hello")
    assert result == "译文：你好"

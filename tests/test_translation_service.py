"""翻译服务测试：学术提示词与批量翻译（省时省钱）。"""

from __future__ import annotations

from app.services.translation_service import TranslationService


class FakeChatLLM:
    def __init__(self, response: str = "译文：你好") -> None:
        self.response = response
        self.last_messages: list[dict] | None = None

    async def chat(self, messages, **kwargs):
        self.last_messages = messages
        return self.response


async def test_translate_paragraph_uses_academic_prompt():
    llm = FakeChatLLM()
    service = TranslationService(llm=llm)
    result = await service.translate_paragraph("Hello", "zh")
    assert result == "译文：你好"
    system = llm.last_messages[0]["content"]
    assert "学术论文" in system
    assert "术语" in system
    assert "中文" in system
    assert "编号" in system


async def test_translate_paragraph_maps_language_name():
    llm = FakeChatLLM()
    service = TranslationService(llm=llm)
    await service.translate_paragraph("你好", "en")
    assert "英文" in llm.last_messages[0]["content"]


class FakeBatchLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


async def test_translate_paragraphs_batches_in_order():
    llm = FakeBatchLLM(['["译文一", "译文二"]', '["译文三", "译文四"]'])
    service = TranslationService(llm=llm)
    paragraphs = ["P1", "P2", "P3", "P4"]
    translated = [
        (index, text)
        async for index, text in service.translate_paragraphs(
            paragraphs, target_lang="zh", batch_size=2
        )
    ]
    assert translated == [
        (0, "译文一"),
        (1, "译文二"),
        (2, "译文三"),
        (3, "译文四"),
    ]
    assert llm.calls == 2  # 4 段只发 2 次请求


async def test_translate_paragraphs_strips_json_code_fence():
    llm = FakeBatchLLM(['```json\n["译文一"]\n```'])
    service = TranslationService(llm=llm)
    translated = [
        text
        async for _, text in service.translate_paragraphs(["P1"], batch_size=4)
    ]
    assert translated == ["译文一"]


async def test_translate_paragraphs_falls_back_on_bad_json():
    llm = FakeChatLLM()  # 返回纯文本，不是 JSON
    service = TranslationService(llm=llm)
    translated = [
        text
        async for _, text in service.translate_paragraphs(["P1"], batch_size=4)
    ]
    assert translated == ["译文：你好"]


async def test_translate_paragraphs_falls_back_on_length_mismatch():
    class ShortLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return '["只有一句"]'
            return "回退译文"

    llm = ShortLLM()
    service = TranslationService(llm=llm)
    translated = [
        text
        async for _, text in service.translate_paragraphs(
            ["One.", "Two."], batch_size=4
        )
    ]
    assert translated == ["回退译文", "回退译文"]

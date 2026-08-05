"""翻译服务测试：学术提示词、多模态识图翻译与批量翻译。"""

from __future__ import annotations

import asyncio

import pytest

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
    assert "Translate the source into Chinese" in system
    assert "Layout fidelity" in system
    assert "THE IMAGE IS AUTHORITATIVE" in system
    assert "URLs" in system and "DOIs" in system
    assert "Output ONLY the translation" in system
    assert llm.last_messages[-1]["content"] == "原文：\nHello"


async def test_translate_paragraph_maps_language_name():
    llm = FakeChatLLM()
    service = TranslationService(llm=llm)
    await service.translate_paragraph("你好", "en")
    assert "Translate the source into English" in (
        llm.last_messages[0]["content"]
    )


async def test_translate_paragraph_with_image_sends_multimodal_content():
    llm = FakeChatLLM("译文")
    service = TranslationService(llm=llm)
    result = await service.translate_paragraph_with_image(
        "Hello", "data:image/png;base64,AAA", "zh"
    )
    assert result == "译文"
    content = llm.last_messages[-1]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "data:image/png;base64,AAA"
    assert content[1]["text"] == "原文：\nHello"


async def test_translate_paragraph_with_image_falls_back_to_text():
    class FlakyLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            content = messages[-1]["content"]
            if isinstance(content, list):
                raise RuntimeError("image unsupported")
            return "回退译文"

    service = TranslationService(llm=FlakyLLM())
    result = await service.translate_paragraph_with_image(
        "Hello", "data:image/png;base64,AAA", "zh"
    )
    assert result == "回退译文"


async def test_translate_paragraphs_with_images_concurrent_yields_in_order():
    class ImageSlowLLM:
        def __init__(self, delays: dict[str, float]) -> None:
            self.delays = delays

        async def chat(self, messages, **kwargs):
            content = messages[-1]["content"]
            text = content[1]["text"] if isinstance(content, list) else content
            key = text.split("原文：\n", 1)[-1]
            await asyncio.sleep(self.delays[key])
            return "T(" + key + ")"

    service = TranslationService(llm=ImageSlowLLM({"slow": 0.2, "fast": 0.01}))
    items = [
        ("slow", "data:image/png;base64,AAA"),
        ("fast", "data:image/png;base64,BBB"),
    ]
    translated = [
        item
        async for item in service.translate_paragraphs_with_images_concurrent(
            items, "zh", max_concurrency=2
        )
    ]
    assert translated == [(1, "T(fast)"), (0, "T(slow)")]


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


class SlowLLM:
    def __init__(self, delays: dict[str, float]) -> None:
        self.delays = delays

    async def chat(self, messages, **kwargs):
        text = messages[-1]["content"]
        if text.startswith("原文：\n"):
            text = text.split("原文：\n", 1)[-1]
        await asyncio.sleep(self.delays[text])
        return f"T({text})"


async def test_translate_paragraphs_concurrent_yields_in_completion_order():
    """并发逐段翻译：谁先完成谁先产出，便于前端尽快显示第一段。"""
    llm = SlowLLM({"slow": 0.2, "fast": 0.01})
    service = TranslationService(llm=llm)
    translated = [
        item
        async for item in service.translate_paragraphs_concurrent(
            ["slow", "fast"], "zh", max_concurrency=2
        )
    ]
    assert translated == [(1, "T(fast)"), (0, "T(slow)")]


class CountingLLM:
    def __init__(self) -> None:
        self.inflight = 0
        self.max_inflight = 0
        self._lock = asyncio.Lock()

    async def chat(self, messages, **kwargs):
        async with self._lock:
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
        await asyncio.sleep(0.02)
        async with self._lock:
            self.inflight -= 1
        return "ok"


async def test_translate_paragraphs_concurrent_limits_concurrency():
    llm = CountingLLM()
    service = TranslationService(llm=llm)
    translated = [
        item
        async for item in service.translate_paragraphs_concurrent(
            ["p1", "p2", "p3", "p4", "p5", "p6"],
            "zh",
            max_concurrency=2,
        )
    ]
    assert len(translated) == 6
    assert llm.max_inflight <= 2


async def test_translate_paragraphs_concurrent_raises_on_error():
    class FailingLLM:
        async def chat(self, messages, **kwargs):
            text = messages[-1]["content"]
            if "bad" in text:
                raise RuntimeError("boom")
            return "ok"

    service = TranslationService(llm=FailingLLM())
    with pytest.raises(RuntimeError, match="boom"):
        async for _ in service.translate_paragraphs_concurrent(
            ["ok1", "bad", "ok2"], "zh", max_concurrency=2
        ):
            pass

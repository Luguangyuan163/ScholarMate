"""LLM 翻译服务：学术提示词 + 批量翻译（省时省钱），Agent 工具依赖。"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

from app.core.llm_client import BaseLLMClient

_LANG_NAMES = {"zh": "中文", "en": "英文"}
_ACADEMIC_SYSTEM_PROMPT = (
    "你是资深学术论文翻译专家。将下面的文本翻译为{lang}，要求："
    "1. 术语准确、专业，专有名词与缩写遵循学界惯例"
    "（如 LoRA、fine-tuning、attention 等可保留英文或按惯例翻译）；"
    "2. 保持学术语体，严谨通顺，符合{lang}学术表达习惯；"
    "3. 保留原文的段落结构、公式、引用编号与图表标记"
    "（如 Fig. 3、Table 2、[1]）；"
    "4. 忠于原文，不增删内容，不省略；只输出译文，不要任何解释。"
)
_BATCH_SYSTEM_PROMPT = (
    "你是资深学术论文翻译专家。将下面编号的段落逐段翻译为{lang}，"
    "要求：术语准确专业、保持学术语体、保留公式/引用/编号；"
    "只输出 JSON 字符串数组，元素顺序与段落编号一一对应，不要任何其他内容。"
)


class TranslationService:
    def __init__(self, llm: BaseLLMClient) -> None:
        self._llm = llm

    async def translate_paragraph(self, text: str, target_lang: str = "zh") -> str:
        messages = [
            {
                "role": "system",
                "content": _ACADEMIC_SYSTEM_PROMPT.format(
                    lang=_lang_name(target_lang)
                ),
            },
            {"role": "user", "content": text},
        ]
        return (await self._llm.chat(messages)).strip()

    async def translate_paragraphs(
        self,
        paragraphs: list[str],
        target_lang: str = "zh",
        batch_size: int = 4,
    ) -> AsyncIterator[tuple[int, str]]:
        """按批翻译段落，产出 (原始下标, 译文)；批量 JSON 失败时回退逐段翻译。"""
        for start in range(0, len(paragraphs), batch_size):
            batch = paragraphs[start : start + batch_size]
            translated = await self._translate_batch(batch, target_lang)
            for offset, text in enumerate(translated):
                yield start + offset, text

    async def translate_paragraphs_concurrent(
        self,
        paragraphs: list[str],
        target_lang: str = "zh",
        max_concurrency: int = 4,
    ) -> AsyncIterator[tuple[int, str]]:
        """逐段并发翻译，谁先完成谁先产出；任一失败则终止并取消其余任务。"""
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _translate_one(index: int, text: str) -> tuple[int, str]:
            async with semaphore:
                return index, await self.translate_paragraph(text, target_lang)

        tasks = [
            asyncio.create_task(_translate_one(index, text))
            for index, text in enumerate(paragraphs)
        ]
        try:
            for task in asyncio.as_completed(tasks):
                yield await task
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    async def _translate_batch(
        self, batch: list[str], target_lang: str
    ) -> list[str]:
        numbered = "\n".join(
            f"{index + 1}. {paragraph}" for index, paragraph in enumerate(batch)
        )
        messages = [
            {
                "role": "system",
                "content": _BATCH_SYSTEM_PROMPT.format(lang=_lang_name(target_lang)),
            },
            {"role": "user", "content": numbered},
        ]
        raw = (await self._llm.chat(messages)).strip()
        parsed = _parse_json_array(raw)
        if parsed is not None and len(parsed) == len(batch):
            return [str(item) for item in parsed]
        return [
            await self.translate_paragraph(paragraph, target_lang)
            for paragraph in batch
        ]


def _lang_name(target_lang: str) -> str:
    return _LANG_NAMES.get(target_lang, target_lang)


def _parse_json_array(raw: str) -> list | None:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, list) else None

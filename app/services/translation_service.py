"""LLM 翻译服务：千问多模态翻译（识图）+ 学术提示词 + 断点续翻，Agent 工具依赖。"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

from app.core.llm_client import BaseLLMClient

_LANG_NAMES = {"zh": "Chinese", "en": "English"}
_TRANSLATE_SYSTEM_PROMPT = (
    "You are a professional academic-paper translation engine with vision capability. "
    "The user provides an image (a cropped paragraph region from the paper page) and the "
    "extracted text of the same region. THE IMAGE IS AUTHORITATIVE: when the extracted text "
    "contains placeholder characters or extraction artifacts (e.g., '?' or '\uff1f' in place "
    "of math symbols like \u0394, \u2208, \u226a, \u00d7, superscripts, or broken glyphs), read "
    "the image and reconstruct the correct symbols and characters. "
    "Translate the source into {lang}, following these rules:\n"
    "1. Accuracy: translate faithfully and completely; do not omit, add, summarize, "
    "explain, or correct the content.\n"
    "2. Layout fidelity: output exactly ONE paragraph, with no bullet or numbered lists, "
    "no headings, no blank lines, no markers like \u201c译文：\u201d, and no markdown syntax. "
    "Keep the translation concise and close to the source length so it fits the original "
    "text area without overflowing or overlapping neighboring text.\n"
    "3. Keep the following verbatim (do not translate, rephrase, or split them): URLs, "
    "links, DOIs, arXiv IDs, emails, file paths, citation numbers and markers (e.g., [1], "
    "[2,3]), formulas and math (e.g., \u0394W = BA), LaTeX/code snippets, unit symbols, "
    "model names, and abbreviations commonly kept in English (e.g., LoRA, CNN, GPU, API).\n"
    "4. Preserve references to figures and tables (e.g., Fig. 3, Table 2).\n"
    "5. Output ONLY the translation. Do not repeat the source; do not add anything else."
)
_BATCH_SYSTEM_PROMPT = (
    "Translate the numbered academic paragraphs to {lang}. "
    "Output only a JSON array of translations, one item per paragraph, "
    "in the same order. Do not output anything else."
)


class TranslationService:
    def __init__(self, llm: BaseLLMClient) -> None:
        self._llm = llm

    async def translate_paragraph(self, text: str, target_lang: str = "zh") -> str:
        messages = [
            {
                "role": "system",
                "content": _TRANSLATE_SYSTEM_PROMPT.format(
                    lang=_lang_name(target_lang)
                ),
            },
            {"role": "user", "content": "原文：\n" + text},
        ]
        return (await self._llm.chat(messages)).strip()

    async def translate_paragraph_with_image(
        self,
        text: str,
        image_data_url: str,
        target_lang: str = "zh",
    ) -> str:
        """多模态翻译：把段落区域截图与原文字一起发给千问 VL，失败时回退纯文本。"""
        messages = [
            {
                "role": "system",
                "content": _TRANSLATE_SYSTEM_PROMPT.format(
                    lang=_lang_name(target_lang)
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": "原文：\n" + text},
                ],
            },
        ]
        try:
            return (await self._llm.chat(messages)).strip()
        except Exception:
            # 图片不支持/调用失败时退回纯文本翻译，保证流程不断
            return await self.translate_paragraph(text, target_lang)

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

    async def translate_paragraphs_with_images_concurrent(
        self,
        items: list[tuple[str, str]],
        target_lang: str = "zh",
        max_concurrency: int = 4,
    ) -> AsyncIterator[tuple[int, str]]:
        """并发多模态翻译：items 为 (原文, 图片 data URL)，谁先完成谁先产出。"""
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _translate_one(
            index: int, item: tuple[str, str]
        ) -> tuple[int, str]:
            async with semaphore:
                return index, await self.translate_paragraph_with_image(
                    item[0], item[1], target_lang
                )

        tasks = [
            asyncio.create_task(_translate_one(index, item))
            for index, item in enumerate(items)
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
            {"role": "user", "content": "原文：\n" + numbered},
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

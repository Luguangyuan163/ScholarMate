"""Agent 工具定义与注册（P3）。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from starlette.concurrency import run_in_threadpool

ToolFunc = Callable[..., Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: ToolFunc = field(repr=False)

    def to_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def build_tools(arxiv, s2, openalex, embedding, vector_store, translation) -> list[Tool]:
    return [
        Tool(
            name="search_arxiv",
            description="在 arXiv 检索论文，返回标题/作者/年份/链接（不含引用量）",
            parameters=_search_params(),
            func=_make_search_arxiv(arxiv),
        ),
        Tool(
            name="search_semantic_scholar",
            description=(
                "在 Semantic Scholar 检索论文，返回引用量，可用于按引用量排序；"
                "Semantic Scholar 不可用时自动回退 OpenAlex"
            ),
            parameters=_search_params(),
            func=_make_search_s2(s2, openalex),
        ),
        Tool(
            name="search_local",
            description="在本地论文库做语义检索，返回最相关的段落及来源",
            parameters=_search_params(),
            func=_make_search_local(embedding, vector_store),
        ),
        Tool(
            name="get_paper_detail",
            description=(
                "获取论文详情（摘要、引用量、年份），paper_id 来自检索结果；"
                "Semantic Scholar 不可用时自动回退 OpenAlex"
            ),
            parameters={
                "type": "object",
                "properties": {"paper_id": {"type": "string"}},
                "required": ["paper_id"],
            },
            func=_make_paper_detail(s2, openalex),
        ),
        Tool(
            name="translate_text",
            description="将指定文本翻译为目标语言（默认中文）",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "target_lang": {"type": "string"},
                },
                "required": ["text"],
            },
            func=_make_translate(translation),
        ),
    ]


def _search_params() -> dict:
    return {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }


def _make_search_arxiv(arxiv):
    async def search_arxiv(query: str, max_results: int = 5) -> str:
        items = await arxiv.search(query, max_results=int(max_results))
        payload = [
            {
                "title": item.title,
                "authors": item.authors,
                "year": item.year,
                "external_id": item.external_id,
                "url": item.url,
            }
            for item in items
        ]
        return json.dumps(payload, ensure_ascii=False)

    return search_arxiv


def _make_search_s2(s2, openalex):
    async def search_semantic_scholar(query: str, limit: int = 5) -> str:
        items = await _metadata_search(s2, openalex, query, int(limit))
        payload = [
            {
                "title": item.title,
                "source": item.source,
                "year": item.year,
                "citation_count": item.citation_count,
                "external_id": item.external_id,
                "url": item.url,
            }
            for item in items
        ]
        return json.dumps(payload, ensure_ascii=False)

    return search_semantic_scholar


async def _metadata_search(s2, openalex, query: str, limit: int):
    if s2 is not None:
        try:
            return await s2.search(query, limit=limit)
        except httpx.HTTPError:
            pass
    return await openalex.search(query, limit=limit)


def _make_search_local(embedding, vector_store):
    async def search_local(query: str, top_k: int = 3) -> str:
        vectors = await embedding.embed_texts([query])
        hits = await run_in_threadpool(vector_store.search, vectors[0], int(top_k))
        payload = [
            {
                "pdf_id": hit.pdf_id,
                "name": hit.name,
                "chunk_index": hit.chunk_index,
                "distance": round(hit.distance, 4),
                "text": hit.document[:300],
            }
            for hit in hits
        ]
        return json.dumps(payload, ensure_ascii=False)

    return search_local


def _make_paper_detail(s2, openalex):
    async def get_paper_detail(paper_id: str) -> str:
        data = await _metadata_detail(s2, openalex, paper_id)
        return json.dumps(
            {
                "title": data.get("title"),
                "abstract": data.get("abstract"),
                "year": data.get("year"),
                "citation_count": data.get("citationCount"),
                "url": data.get("url"),
            },
            ensure_ascii=False,
        )

    return get_paper_detail


async def _metadata_detail(s2, openalex, paper_id: str) -> dict:
    if s2 is not None:
        try:
            return await s2.get_paper_detail(paper_id)
        except httpx.HTTPError:
            pass
    return await openalex.get_paper_detail(paper_id)


def _make_translate(translation):
    async def translate_text(text: str, target_lang: str = "zh") -> str:
        translated = await translation.translate_paragraph(text, target_lang)
        return json.dumps({"translation": translated}, ensure_ascii=False)

    return translate_text

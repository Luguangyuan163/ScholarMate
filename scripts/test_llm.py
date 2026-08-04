"""LLM 连通性验证脚本（P1 使用）。

用法:
    python scripts/test_llm.py
"""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.core.llm_client import get_llm_client


async def verify() -> str:
    settings = Settings()
    api_key = (
        settings.deepseek_api_key
        if settings.llm_provider == "deepseek"
        else settings.dashscope_api_key
    )
    if not api_key:
        return "未配置 API Key，请先填写 .env"
    client = get_llm_client(settings)
    return await client.chat([{"role": "user", "content": "请只回复两个字：正常"}])


if __name__ == "__main__":
    print(asyncio.run(verify()))

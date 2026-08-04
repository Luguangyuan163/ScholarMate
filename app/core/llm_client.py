"""多模型 LLM 客户端工厂（DeepSeek / Qwen 兼容 OpenAI SDK）。

openai 依赖在首次调用时惰性导入，避免骨架阶段强制安装。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.config import Settings

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class BaseLLMClient:
    provider: str
    model: str

    async def chat(self, messages: list[dict], **kwargs) -> str:
        raise NotImplementedError

    async def astream_chat(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        raise NotImplementedError


@dataclass
class OpenAICompatibleClient(BaseLLMClient):
    api_key: str
    base_url: str
    model: str
    provider: str
    _client: object | None = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    async def chat(self, messages: list[dict], **kwargs) -> str:
        response = await self._get_client().chat.completions.create(
            model=self.model, messages=messages, **kwargs
        )
        return response.choices[0].message.content or ""

    async def astream_chat(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        stream = await self._get_client().chat.completions.create(
            model=self.model, messages=messages, stream=True, **kwargs
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content


def get_llm_client(settings: Settings) -> BaseLLMClient:
    if settings.llm_provider == "deepseek":
        return OpenAICompatibleClient(
            api_key=settings.deepseek_api_key,
            base_url=DEEPSEEK_BASE_URL,
            model=settings.deepseek_model,
            provider="deepseek",
        )
    if settings.llm_provider == "qwen":
        return OpenAICompatibleClient(
            api_key=settings.dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            model=settings.dashscope_model,
            provider="qwen",
        )
    if settings.llm_provider == "claude":
        raise NotImplementedError("Claude 客户端暂未接入（可选模型）")
    raise ValueError(f"未知 LLM_PROVIDER: {settings.llm_provider}")

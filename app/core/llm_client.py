"""多模型 LLM 客户端工厂（P1 接入，依赖按需导入）。

DeepSeek 与 DashScope 均兼容 OpenAI SDK；Claude 使用 anthropic SDK。
骨架阶段仅提供工厂结构与模型名解析，真实对话能力在 P1 实现。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings


@dataclass
class LLMClient:
    provider: str
    model: str

    async def chat(self, messages: list[dict], **kwargs) -> str:
        raise NotImplementedError("LLM 对话将在 P1（test_llm.py 验证）接入")


def get_llm_client(settings: Settings) -> LLMClient:
    return LLMClient(provider=settings.llm_provider, model=_resolve_model(settings))


def _resolve_model(settings: Settings) -> str:
    if settings.llm_provider == "qwen":
        return settings.dashscope_model
    if settings.llm_provider == "claude":
        return settings.anthropic_model
    return settings.deepseek_model

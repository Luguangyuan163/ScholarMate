"""LLM 客户端工厂与对话测试（openai 依赖通过注入替身规避）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.core.llm_client import (
    BaseLLMClient,
    OpenAICompatibleClient,
    _parse_arguments,
    get_llm_client,
)


class FakeStreamChunk:
    def __init__(self, content: str) -> None:
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=content))]


class FakeStream:
    def __init__(self, contents: list[str]) -> None:
        self._contents = contents

    async def __aiter__(self):
        for content in self._contents:
            yield FakeStreamChunk(content)


class FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        if kwargs.get("stream"):
            return FakeStream(["你", "好"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


async def test_chat_returns_content():
    completions = FakeCompletions("你好")
    client = OpenAICompatibleClient(
        api_key="k",
        base_url="http://x",
        model="deepseek-v4-flash",
        provider="deepseek",
        _client=FakeClient(completions),
    )
    result = await client.chat([{"role": "user", "content": "hi"}])
    assert result == "你好"
    assert completions.last_kwargs["model"] == "deepseek-v4-flash"


async def test_astream_chat_yields_content():
    completions = FakeCompletions("")
    client = OpenAICompatibleClient(
        api_key="k",
        base_url="http://x",
        model="deepseek-v4-flash",
        provider="deepseek",
        _client=FakeClient(completions),
    )
    chunks = [chunk async for chunk in client.astream_chat([{"role": "user", "content": "hi"}])]
    assert chunks == ["你", "好"]


async def test_chat_with_tools_parses_tool_calls():
    class FakeToolCompletions:
        async def create(self, **kwargs):
            self.last_kwargs = kwargs
            tool_calls = [
                SimpleNamespace(
                    id="call-1",
                    function=SimpleNamespace(
                        name="add", arguments=json.dumps({"a": 1, "b": 2})
                    ),
                )
            ]
            message = SimpleNamespace(content=None, tool_calls=tool_calls)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake = FakeToolCompletions()
    client = OpenAICompatibleClient(
        api_key="k",
        base_url="http://x",
        model="deepseek-v4-flash",
        provider="deepseek",
        _client=SimpleNamespace(chat=SimpleNamespace(completions=fake)),
    )
    response = await client.chat_with_tools(
        [{"role": "user", "content": "1+2?"}],
        tools=[{"type": "function", "function": {"name": "add"}}],
    )
    assert response.content == ""
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "add"
    assert response.tool_calls[0].arguments == {"a": 1, "b": 2}
    assert fake.last_kwargs["tools"][0]["function"]["name"] == "add"


def test_factory_deepseek():
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        deepseek_api_key="k",
        deepseek_model="deepseek-v4-flash",
    )
    client = get_llm_client(settings)
    assert client.provider == "deepseek"
    assert client.model == "deepseek-v4-flash"
    assert client.base_url == "https://api.deepseek.com"


def test_factory_qwen():
    settings = Settings(
        _env_file=None,
        llm_provider="qwen",
        dashscope_api_key="k",
        dashscope_model="qwen-plus",
    )
    client = get_llm_client(settings)
    assert client.provider == "qwen"
    assert client.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_factory_unknown_provider_raises():
    settings = Settings(_env_file=None, llm_provider="nope")
    with pytest.raises(ValueError):
        get_llm_client(settings)


def test_factory_claude_not_implemented():
    settings = Settings(_env_file=None, llm_provider="claude", anthropic_api_key="k")
    with pytest.raises(NotImplementedError):
        get_llm_client(settings)


def test_parse_arguments_handles_invalid_json():
    assert _parse_arguments("not json") == {}
    assert _parse_arguments(None) == {}


async def test_chat_with_tools_without_tool_calls():
    class FakeNoToolsCompletions:
        async def create(self, **kwargs):
            message = SimpleNamespace(content="plain answer", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = OpenAICompatibleClient(
        api_key="k",
        base_url="http://x",
        model="deepseek-v4-flash",
        provider="deepseek",
        _client=SimpleNamespace(chat=SimpleNamespace(completions=FakeNoToolsCompletions())),
    )
    response = await client.chat_with_tools([{"role": "user", "content": "hi"}], tools=[])
    assert response.content == "plain answer"
    assert response.tool_calls == []


def test_base_client_methods_not_implemented():
    client = BaseLLMClient()

    async def _run():
        calls = []
        for method in (
            client.chat([{"role": "user", "content": "hi"}]),
            client.astream_chat([{"role": "user", "content": "hi"}]),
            client.chat_with_tools([{"role": "user", "content": "hi"}], tools=[]),
        ):
            try:
                await method
            except NotImplementedError:
                calls.append(True)
        return calls

    import asyncio

    assert asyncio.run(_run()) == [True, True, True]

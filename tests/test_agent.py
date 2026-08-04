"""ReAct Agent 循环、工具与 SSE 端点测试。"""

from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from app.agent.agent_loop import agent_loop
from app.agent.tools import Tool, build_tools
from app.core.llm_client import LLMResponse, ToolCall
from app.main import create_app
from app.schemas.search import PaperItem


class FakeLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.tools_seen = None

    async def chat_with_tools(self, messages, tools, **kwargs):
        self.tools_seen = tools
        return self.responses.pop(0)

    async def chat(self, messages, **kwargs):
        return "ok"


def _add_tool() -> Tool:
    async def _add(a: int, b: int) -> str:
        return json.dumps({"sum": a + b})

    return Tool(name="add", description="加法", parameters={}, func=_add)


async def test_agent_loop_tool_then_answer():
    llm = FakeLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="1", name="add", arguments={"a": 1, "b": 2})],
            ),
            LLMResponse(content="结果是 3", tool_calls=[]),
        ]
    )
    events = [event async for event in agent_loop("1+2?", [_add_tool()], llm, max_iter=5)]
    assert [event["type"] for event in events] == [
        "tool_call",
        "tool_result",
        "message",
        "done",
    ]
    assert json.loads(events[1]["content"]) == {"sum": 3}
    assert events[2]["content"] == "结果是 3"
    assert llm.tools_seen[0]["function"]["name"] == "add"


async def test_agent_loop_max_iterations():
    always_call = LLMResponse(
        content="", tool_calls=[ToolCall(id="1", name="add", arguments={"a": 1, "b": 2})]
    )
    llm = FakeLLM([always_call, always_call, always_call])
    events = [event async for event in agent_loop("x", [_add_tool()], llm, max_iter=2)]
    assert events[-1]["type"] == "error"
    assert "迭代" in events[-1]["content"]


async def test_agent_loop_tool_error_reported():
    async def _boom(a: int) -> str:
        raise RuntimeError("boom")

    tool = Tool(name="boom", description="boom", parameters={}, func=_boom)
    llm = FakeLLM(
        [
            LLMResponse(content="", tool_calls=[ToolCall(id="1", name="boom", arguments={"a": 1})]),
            LLMResponse(content="完成", tool_calls=[]),
        ]
    )
    events = [event async for event in agent_loop("x", [tool], llm, max_iter=5)]
    assert "boom" in json.loads(events[1]["content"])["error"]


async def test_search_arxiv_tool_returns_json():
    class FakeArxiv:
        async def search(self, query, max_results=10, year_from=None, year_to=None):
            return [
                PaperItem(
                    title="LoRA Paper",
                    source="arxiv",
                    external_id="2106.09685",
                    year=2021,
                )
            ]

    tools = build_tools(
        arxiv=FakeArxiv(),
        s2=None,
        openalex=None,
        embedding=None,
        vector_store=None,
        translation=None,
    )
    output = await tools[0].func(query="LoRA", max_results=5)
    payload = json.loads(output)
    assert payload[0]["title"] == "LoRA Paper"
    assert payload[0]["external_id"] == "2106.09685"


async def test_search_s2_tool_falls_back_to_openalex():
    class BrokenS2:
        async def search(self, query, limit=10):
            raise httpx.HTTPStatusError(
                "429",
                request=httpx.Request("GET", "https://api.semanticscholar.org"),
                response=httpx.Response(429),
            )

    class FakeOpenAlex:
        async def search(self, query, limit=10):
            return [
                PaperItem(
                    title="OpenAlex Paper",
                    source="openalex",
                    external_id="W1",
                    year=2022,
                    citation_count=88,
                )
            ]

    tools = build_tools(
        arxiv=None,
        s2=BrokenS2(),
        openalex=FakeOpenAlex(),
        embedding=None,
        vector_store=None,
        translation=None,
    )
    output = await tools[1].func(query="LoRA", limit=5)
    payload = json.loads(output)
    assert payload[0]["source"] == "openalex"
    assert payload[0]["citation_count"] == 88


def test_sse_agent_endpoint_streams_events(app_settings):
    app = create_app(app_settings)
    app.state.llm_client = FakeLLM([LLMResponse(content="你好", tool_calls=[])])
    with TestClient(app) as client:
        resp = client.post("/api/agent/chat", json={"query": "你好"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: message" in resp.text
    assert "你好" in resp.text

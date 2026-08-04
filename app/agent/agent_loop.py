"""ReAct 主循环（P3）：Think -> Act -> Observe -> Loop -> Synthesize。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import Tool
from app.core.llm_client import BaseLLMClient, ToolCall


async def agent_loop(
    user_query: str,
    tools: list[Tool],
    llm: BaseLLMClient,
    max_iter: int = 5,
) -> AsyncIterator[dict]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]
    tool_map = {tool.name: tool for tool in tools}
    specs = [tool.to_spec() for tool in tools]

    for _ in range(max_iter):
        response = await llm.chat_with_tools(messages, tools=specs)
        if not response.tool_calls:
            yield {"type": "message", "content": response.content}
            yield {"type": "done"}
            return

        assistant_calls = []
        tool_messages = []
        for call in response.tool_calls:
            yield {"type": "tool_call", "name": call.name, "arguments": call.arguments}
            result = await _execute_tool(tool_map, call)
            yield {"type": "tool_result", "name": call.name, "content": result}
            assistant_calls.append(_assistant_call(call))
            tool_messages.append({"tool_call_id": call.id, "content": result})

        messages.append(
            {"role": "assistant", "content": None, "tool_calls": assistant_calls}
        )
        messages.extend({"role": "tool", **msg} for msg in tool_messages)

    yield {"type": "error", "content": "达到最大迭代次数，请精简问题后重试"}


async def _execute_tool(tool_map: dict[str, Tool], call: ToolCall) -> str:
    tool = tool_map.get(call.name)
    if tool is None:
        return json.dumps({"error": f"未知工具: {call.name}"}, ensure_ascii=False)
    try:
        return await tool.func(**call.arguments)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def _assistant_call(call: ToolCall) -> dict:
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": json.dumps(call.arguments, ensure_ascii=False),
        },
    }

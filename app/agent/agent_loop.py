"""ReAct 主循环（P3 实现）。

骨架阶段仅提供签名与流程注释，真实行为在接入 LLM 客户端后实现。
"""

from __future__ import annotations

from collections.abc import AsyncIterator


async def agent_loop(user_query: str, tools: list, max_iter: int = 5) -> AsyncIterator[str]:
    # Think -> Act -> Observe -> Loop -> Synthesize
    raise NotImplementedError("ReAct 主循环将在 P3 接入")

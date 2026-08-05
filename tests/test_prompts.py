"""System Prompt 测试：当前年份注入。"""

from __future__ import annotations

from app.agent.prompts import build_system_prompt


def test_build_system_prompt_injects_current_year():
    prompt = build_system_prompt(2026)
    assert "2026 年" in prompt
    assert "去年」指 2025 年" in prompt


def test_build_system_prompt_mentions_year_params():
    prompt = build_system_prompt(2026)
    assert "year_from/year_to" in prompt

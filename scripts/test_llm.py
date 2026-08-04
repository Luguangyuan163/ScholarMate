"""LLM 连通性验证脚本（P1 接入 LLM 客户端后使用）。

用法:
    python scripts/test_llm.py
"""

from __future__ import annotations

from app.config import Settings


def main() -> None:
    settings = Settings()
    if not settings.deepseek_api_key:
        print("未配置 DEEPSEEK_API_KEY，请先填写 .env")
        return
    print(f"LLM 配置就绪: provider={settings.llm_provider}, model={settings.deepseek_model}")
    print("真实连通性测试将在 P1 接入 LLM 客户端后启用")


if __name__ == "__main__":
    main()

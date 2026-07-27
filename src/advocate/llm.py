"""Provider factory — hybrid: free OpenRouter default, Claude opt-in.

`build_system_prefix` returns a cache-friendly system message: on Anthropic it
marks the stable prefix with `cache_control` so it is cached across every posting
extraction (large, repeated vocabulary block). On OpenRouter it is a plain string
(free routes give only incidental prefix caching).
"""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage


def get_llm(provider: str, model: str, temperature: float = 0.0) -> BaseChatModel:
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, temperature=temperature, max_tokens=2048)

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )


def build_system_prefix(provider: str, text: str) -> SystemMessage:
    """Stable, reusable system prefix — cached on Anthropic via cache_control."""
    if provider == "anthropic":
        return SystemMessage(
            content=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
        )
    return SystemMessage(content=text)

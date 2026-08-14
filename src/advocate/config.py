"""Runtime configuration — provider/model selection in one place."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODELS = {
    "openrouter": "openai/gpt-oss-120b:free",
    "anthropic": "claude-sonnet-4-6",
}


@dataclass(frozen=True)
class Config:
    provider: str
    model: str
    keywords: str
    location: str
    geo_id: str
    top_n: int


def assert_key(provider: str) -> None:
    needed = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENROUTER_API_KEY"
    if not os.environ.get(needed):
        hint = (
            "free key: https://openrouter.ai/keys"
            if needed == "OPENROUTER_API_KEY"
            else "https://console.anthropic.com/"
        )
        print(f"✋ Set {needed} ({hint}) in .env or your shell.")
        sys.exit(1)


def resolve(
    *,
    provider: str | None,
    model: str | None,
    keywords: str,
    location: str,
    geo_id: str,
    top_n: int,
) -> Config:
    provider = (provider or os.environ.get("JOB_AGENT_PROVIDER") or "openrouter").lower()
    if provider not in DEFAULT_MODELS:
        provider = "openrouter"
    model = model or os.environ.get("JOB_AGENT_MODEL") or DEFAULT_MODELS[provider]
    return Config(provider, model, keywords, location, geo_id, top_n)

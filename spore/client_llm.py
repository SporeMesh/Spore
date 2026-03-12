from __future__ import annotations

import os
from pathlib import Path

from .llm import LLMConfig, save_config

ENV_KEYS = {
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "xai": "XAI_API_KEY",
}


def resolve_llm_api_key(provider: str, explicit_key: str | None) -> str:
    if explicit_key:
        return explicit_key
    return os.environ.get(ENV_KEYS.get(provider, "SPORE_LLM_API_KEY"), "")


def save_llm_settings(
    *,
    data_dir: Path,
    provider: str,
    api_key: str,
    model: str | None = None,
) -> None:
    if not api_key:
        return
    save_config(
        data_dir,
        LLMConfig(provider=provider, api_key=api_key, model=model or ""),
    )

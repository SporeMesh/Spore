from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".spore"
CONFIG_PATH = CONFIG_DIR / "client.json"
DEFAULT_BASE_URL = os.environ.get("SPORE_API_URL", "https://api.sporemesh.com")


def default_config() -> dict[str, Any]:
    return {
        "base_url": DEFAULT_BASE_URL.rstrip("/"),
        "api_key": "",
        "operator_id": "",
        "wallet_address": "",
        "private_key": "",
        "llm_provider": "",
        "llm_model": "",
        "default_node_id": "",
        "default_node_public_id": "",
        "default_challenge_id": "",
        "default_challenge_slug": "",
    }


def load_config() -> dict[str, Any]:
    config = default_config()
    if CONFIG_PATH.exists():
        stored = json.loads(CONFIG_PATH.read_text())
        if isinstance(stored, dict):
            config.update(stored)
    return config


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    return config


def update_config(**values: Any) -> dict[str, Any]:
    config = load_config()
    for key, value in values.items():
        if value is not None:
            config[key] = value
    return save_config(config)

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_account import Account

from .client_api import BackendClient
from .client_auth import login_with_private_key
from .client_challenge import list_challenges, pick_default_challenge
from .client_detect import detect_node_profile
from .client_llm import resolve_llm_api_key, save_llm_settings
from .client_store import load_config, update_config


def ensure_private_key(explicit_key: str | None, force_new: bool = False) -> tuple[str, bool]:
    config = load_config()
    if explicit_key:
        normalized = explicit_key if explicit_key.startswith("0x") else f"0x{explicit_key}"
        return normalized, False
    if not force_new and config.get("private_key"):
        return str(config["private_key"]), False
    account = Account.create()
    return account.key.hex(), True


def initialize_client(
    *,
    private_key: str | None = None,
    base_url: str | None = None,
    node_public_id: str,
    label: str | None = None,
    challenge_id: str | None = None,
    force_new_wallet: bool = False,
    llm_provider: str = "groq",
    llm_api_key: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    key, generated_key = ensure_private_key(private_key, force_new_wallet)
    auth = login_with_private_key(key, base_url=base_url)
    resolved_llm_api_key = resolve_llm_api_key(llm_provider, llm_api_key)
    detected = detect_node_profile()
    payload = {
        **detected,
        "node_public_id": node_public_id,
        "label": label or detected["label"],
    }
    node = BackendClient(base_url=base_url).post("/api/v1/node/register", auth=True, json_body=payload)
    challenges = list_challenges(BackendClient(base_url=base_url))
    selected = next((item for item in challenges if item.get("id") == challenge_id), None)
    if selected is None:
        selected = pick_default_challenge(challenges)
    save_llm_settings(
        data_dir=Path.home() / ".spore",
        provider=llm_provider,
        api_key=resolved_llm_api_key,
        model=llm_model,
    )
    update_config(
        private_key=key,
        llm_provider=llm_provider if resolved_llm_api_key else "",
        llm_model=llm_model or "",
        default_node_id=node.get("id", ""),
        default_node_public_id=node_public_id,
        default_challenge_id=selected.get("id", "") if selected else "",
        default_challenge_slug=selected.get("slug", "") if selected else "",
    )
    return {
        "generated_private_key": generated_key,
        "wallet_address": auth["wallet_address"],
        "operator_id": auth["operator_id"],
        "llm_provider": llm_provider if resolved_llm_api_key else "",
        "llm_configured": bool(resolved_llm_api_key),
        "node": node,
        "challenge": selected,
    }

from __future__ import annotations

from typing import Any

from .client_api import BackendClient

STATUS_PRIORITY = {
    "active": 0,
    "scheduled": 1,
    "closed": 2,
    "paid": 3,
    "draft": 4,
}


def list_challenges(client: BackendClient | None = None) -> list[dict[str, Any]]:
    backend = client or BackendClient()
    payload = backend.get("/api/v1/challenge")
    return payload if isinstance(payload, list) else []


def pick_default_challenge(challenges: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not challenges:
        return None

    def rank(challenge: dict[str, Any]) -> tuple[int, float, str]:
        return (
            STATUS_PRIORITY.get(str(challenge.get("status", "")), 99),
            -float(challenge.get("prize_pool") or 0),
            str(challenge.get("end_at") or ""),
        )

    return sorted(challenges, key=rank)[0]

from __future__ import annotations

from spore.client_challenge import pick_default_challenge
from spore.client_store import default_config


def test_default_config_includes_init_fields() -> None:
    config = default_config()

    assert config["private_key"] == ""
    assert config["default_challenge_id"] == ""
    assert config["default_challenge_slug"] == ""


def test_pick_default_challenge_prefers_active_highest_prize() -> None:
    challenge = pick_default_challenge(
        [
            {"id": "scheduled-low", "status": "scheduled", "prize_pool": 100},
            {"id": "active-low", "status": "active", "prize_pool": 10},
            {"id": "active-high", "status": "active", "prize_pool": 50},
        ]
    )

    assert challenge is not None
    assert challenge["id"] == "active-high"

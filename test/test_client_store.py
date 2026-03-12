from __future__ import annotations

import json
from pathlib import Path

from spore import client_store


def test_load_config_uses_defaults_when_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(client_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(client_store, "CONFIG_PATH", tmp_path / "client.json")

    config = client_store.load_config()

    assert config["base_url"] == client_store.DEFAULT_BASE_URL
    assert config["api_key"] == ""


def test_update_config_writes_json(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(client_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(client_store, "CONFIG_PATH", tmp_path / "client.json")

    updated = client_store.update_config(api_key="abc123", operator_id="op_1")

    assert updated["api_key"] == "abc123"
    assert json.loads((tmp_path / "client.json").read_text())["operator_id"] == "op_1"

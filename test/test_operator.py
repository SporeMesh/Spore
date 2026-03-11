"""Tests for the auto-operator."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from spore.operator import AutoOperator, ReleaseManifest


def test_fetch_manifest(monkeypatch):
    payload = io.BytesIO(
        b'{"version":"0.4.1","pip_spec":"sporemesh==0.4.1","instructions":[]}'
    )

    class FakeResponse:
        def __enter__(self):
            return payload

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: FakeResponse()
    )
    operator = AutoOperator(
        manifest_url="https://example.com/release.json",
        current_version="0.4.0",
        enabled=True,
    )
    manifest = operator.fetch_manifest()
    assert isinstance(manifest, ReleaseManifest)
    assert manifest.version == "0.4.1"


def test_apply_update_runs_pip_and_workspace_instruction(tmp_path, monkeypatch):
    commands = []

    def fake_run(cmd, check):
        commands.append(cmd)
        return None

    monkeypatch.setattr("subprocess.run", fake_run)
    operator = AutoOperator(
        manifest_url="https://example.com/release.json",
        current_version="0.4.0",
        enabled=True,
        workdir=tmp_path,
    )
    manifest = ReleaseManifest(
        version="0.4.1",
        pip_spec="sporemesh==0.4.1",
        instructions=["copy_workspace"],
    )
    assert operator.apply_update(manifest) is True
    assert commands == [
        [sys.executable, "-m", "pip", "install", "--upgrade", "sporemesh==0.4.1"]
    ]
    for filename in ("train.py", "prepare.py", "batching.py"):
        assert (Path(tmp_path) / filename).exists()

"""Tests for release manifest generation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_generate_release_manifest(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "misc" / "generate_release_manifest.py"
    result = subprocess.run(
        [sys.executable, str(script), "9.9.9"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    manifest = json.loads((tmp_path / "release-manifest.json").read_text())
    assert manifest["version"] == "9.9.9"
    assert manifest["pip_spec"] == "sporemesh==9.9.9"
    assert manifest["instructions"] == ["copy_workspace", "backfill_tasks"]

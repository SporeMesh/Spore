"""Tests for daemon CLI command forwarding."""

from __future__ import annotations

from click.testing import CliRunner

import spore.cli as cli_module
import spore.daemon as daemon_module


def test_start_help_matches_run_modes():
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["start", "--help"])

    assert result.exit_code == 0
    assert "--web-port" in result.output
    assert "--no-train" in result.output
    assert "--verify-only" in result.output
    assert "--enable-cache" in result.output


def test_start_forwards_runtime_flags(tmp_path, monkeypatch):
    runner = CliRunner()
    launched: dict[str, object] = {}

    class FakeProc:
        pid = 43210

    def fake_popen(cmd, stdout, stderr, start_new_session):
        launched["cmd"] = cmd
        launched["start_new_session"] = start_new_session
        return FakeProc()

    monkeypatch.setattr(daemon_module, "PID_FILE", tmp_path / "spore.pid")
    monkeypatch.setattr(daemon_module, "LOG_FILE", tmp_path / "spore.log")
    monkeypatch.setattr(daemon_module, "is_running", lambda: None)
    monkeypatch.setattr(daemon_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli_module, "ensure_initialized", lambda _data_dir=None: "node")

    data_dir = tmp_path / "node"
    result = runner.invoke(
        cli_module.cli,
        [
            "start",
            "--port",
            "9000",
            "--web-port",
            "9100",
            "--peer",
            "peer.sporemesh.com:7470",
            "--verify-only",
            "--enable-cache",
            "--resource",
            "50",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 0
    assert launched["cmd"] == [
        cli_module.sys.executable,
        "-m",
        "spore.cli",
        "run",
        "--port",
        "9000",
        "--web-port",
        "9100",
        "--peer",
        "peer.sporemesh.com:7470",
        "--verify-only",
        "--resource",
        "50",
        "--data-dir",
        str(data_dir),
        "--enable-cache",
    ]
    assert launched["start_new_session"] is True
    assert daemon_module.PID_FILE.read_text().strip() == "43210"

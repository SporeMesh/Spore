"""Spore daemon — background node management."""

from __future__ import annotations

import os
import signal
import subprocess
import sys

import click
from rich.console import Console

from .node import SPORE_DIR

console = Console()

PID_FILE = SPORE_DIR / "spore.pid"
LOG_FILE = SPORE_DIR / "spore.log"


def is_running() -> int | None:
    """Return the PID if a daemon is running, else None."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


def register_command(cli: click.Group):
    """Register daemon commands on the CLI group."""

    @cli.command()
    @click.option("--port", "-p", default=7470, help="Gossip listen port")
    @click.option("--web-port", "-w", default=8470, help="Explorer web UI port")
    @click.option("--peer", "-c", multiple=True, help="Peer address (host:port)")
    @click.option("--task", "task_id", default="", help="Task ID to follow")
    @click.option(
        "--auto-update/--no-auto-update",
        default=None,
        help="Enable or disable the built-in auto-operator for this daemon",
    )
    @click.option(
        "--no-train", is_flag=True, help="Sync-only mode (no experiment runner)"
    )
    @click.option(
        "--verify-only",
        is_flag=True,
        help="Verifier-only mode (prepare workspace, verify remote experiments, no LLM loop)",
    )
    @click.option(
        "--genesis",
        is_flag=True,
        help="Genesis node: auto-prepare data, skip peer connection",
    )
    @click.option(
        "--resource",
        "-r",
        type=click.IntRange(1, 100),
        default=100,
        help="Resource usage as percent of GPU/CPU (1-100)",
    )
    @click.option(
        "--data-dir", "-d", default=None, help="Data directory (default: ~/.spore)"
    )
    def start(
        port: int,
        web_port: int,
        peer: tuple[str, ...],
        task_id: str,
        auto_update: bool | None,
        no_train: bool,
        verify_only: bool,
        genesis: bool,
        resource: int,
        data_dir: str | None,
    ):
        """Start the Spore node as a background daemon."""
        from pathlib import Path

        from .cli import ensure_initialized

        data_path = Path(data_dir).expanduser() if data_dir else SPORE_DIR
        ensure_initialized(data_path)
        pid = is_running()
        if pid:
            console.print(f"Node is already running. PID: [cyan]{pid}[/]")
            return

        data_path.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            "-m",
            "spore.cli",
            "run",
            "--port",
            str(port),
            "--web-port",
            str(web_port),
        ]
        for p in peer:
            cmd.extend(["--peer", p])
        if task_id:
            cmd.extend(["--task", task_id])
        if auto_update is not None:
            cmd.append("--auto-update" if auto_update else "--no-auto-update")
        if no_train:
            cmd.append("--no-train")
        if verify_only:
            cmd.append("--verify-only")
        if genesis:
            cmd.append("--genesis")
        if resource != 100:
            cmd.extend(["--resource", str(resource)])
        if data_dir:
            cmd.extend(["--data-dir", data_dir])

        with open(LOG_FILE, "a") as log_fh:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        PID_FILE.write_text(str(proc.pid))
        console.print(f"Node started in background. PID: [cyan]{proc.pid}[/]")
        console.print(f"  Log:  [dim]{LOG_FILE}[/]")
        console.print("  Stop: [cyan]spore stop[/]")

    @cli.command()
    def stop():
        """Stop the background Spore node."""
        pid = is_running()
        if not pid:
            console.print("No daemon is running.")
            return

        try:
            os.kill(pid, signal.SIGTERM)
            console.print(f"Sent SIGTERM to PID {pid}.")
        except ProcessLookupError:
            pass
        PID_FILE.unlink(missing_ok=True)
        console.print("Node stopped.")

    @cli.command(name="log")
    @click.option("--follow", "-f", is_flag=True, help="Follow log output")
    @click.option("--tail", "-n", default=50, help="Number of lines to show")
    def show_log(follow: bool, tail: int):
        """Show the daemon log."""
        if not LOG_FILE.exists():
            console.print(
                "No log file found. Start a daemon first with [cyan]spore start[/]."
            )
            return

        cmd = ["tail"]
        if follow:
            cmd.append("-f")
        cmd.extend(["-n", str(tail), str(LOG_FILE)])

        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            pass

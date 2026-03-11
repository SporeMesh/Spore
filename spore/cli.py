"""Spore CLI — interact with your local node."""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import logging.handlers
import os
import signal
import sys
from pathlib import Path

import click
from rich.console import Console

from .node import SPORE_DIR, NodeConfig, SporeNode
from .operator import AutoOperator
from .record import generate_keypair

log = logging.getLogger(__name__)
console = Console()


def ensure_initialized(data_dir: Path | None = None) -> str:
    """Auto-initialize the node if needed. Returns the node ID."""
    data_dir = data_dir or SPORE_DIR
    node_id_path = data_dir / "identity" / "node_id"
    if node_id_path.exists():
        return node_id_path.read_text().strip()

    from nacl.encoding import HexEncoder

    sk, pk_hex = generate_keypair()
    (data_dir / "identity").mkdir(parents=True, exist_ok=True)
    (data_dir / "identity" / "private_key").write_text(
        sk.encode(encoder=HexEncoder).decode("ascii")
    )
    (data_dir / "identity" / "node_id").write_text(pk_hex)
    (data_dir / "db").mkdir(parents=True, exist_ok=True)
    (data_dir / "artifact").mkdir(parents=True, exist_ok=True)
    NodeConfig().save()
    console.print(f"Node initialized. ID: [cyan]{pk_hex[:16]}...[/]")
    return pk_hex


@click.group()
def cli():
    """Spore — Decentralized AI Research Protocol.

    BitTorrent for ML experiments. Run autonomous AI research nodes
    that share results over a peer-to-peer gossip network.
    """
    pass


@cli.command()
@click.option(
    "--auto-update/--no-auto-update",
    default=True,
    help="Enable or disable automatic release checks in the generated config",
)
def init(auto_update: bool):
    """Initialize a new Spore node (generate identity, create directories)."""
    node_id = ensure_initialized()
    config = NodeConfig.load()
    config.auto_update = auto_update
    config.save()
    console.print(f"Node ready. ID: [cyan]{node_id[:16]}...[/]")
    console.print(f"Data directory: [dim]{SPORE_DIR}[/]")


@cli.command()
@click.option("--port", "-p", default=7470, help="Gossip listen port")
@click.option("--web-port", "-w", default=8470, help="Explorer web UI port")
@click.option("--peer", "-c", multiple=True, help="Peer address (host:port)")
@click.option("--task", "task_id", default="", help="Task ID to follow")
@click.option(
    "--auto-update/--no-auto-update",
    default=None,
    help="Enable or disable the built-in auto-operator for this run",
)
@click.option("--no-train", is_flag=True, help="Sync-only mode (no experiment runner)")
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
@click.option(
    "--enable-cache/--disable-cache",
    default=None,
    help="Enable cached explorer read models for heavy sync-only nodes",
)
def run(
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
    enable_cache: bool | None,
):
    """Run the Spore node in the foreground.

    Starts gossip + experiment loop. The node selects frontier experiments,
    calls the configured LLM for proposals, runs training, and publishes results.
    Use --no-train for sync-only mode. Use --genesis for first node setup
    (auto-runs prepare.py, skips peer connection). Configure LLM with `spore set`.
    """
    _configure_logging()
    data_path = Path(data_dir).expanduser() if data_dir else SPORE_DIR
    ensure_initialized(data_path)
    config = NodeConfig.load(data_path / "config.toml")
    config.data_dir = str(data_path)
    config.port = port
    if peer:
        config.peer = list(peer)
    if task_id:
        config.task_id = task_id
    if auto_update is not None:
        config.auto_update = auto_update
    if enable_cache is not None:
        config.enable_cache = enable_cache
    config.save(data_path / "config.toml")

    node = SporeNode(config)

    # Set resource level for train.py subprocess
    os.environ["SPORE_RESOURCE"] = str(resource)

    # Genesis: prepare everything synchronously before starting (no peers to sync with)
    if genesis:
        _auto_prepare()
    elif not Path("train.py").exists():
        # Non-genesis: copy workspace files now, defer data prep to run concurrently
        _copy_workspace_file()

    # Determine training mode
    should_train = False
    should_verify = verify_only
    if verify_only:
        mode = "verifier-only"
    elif no_train:
        mode = "sync-only"
    elif not Path("train.py").exists():
        mode = "sync-only (no train.py in current directory)"
    else:
        from .llm import load_config as load_llm_config

        llm_cfg = load_llm_config(data_path)
        if not llm_cfg.is_configured():
            mode = "sync-only (run 'spore set <provider> <key>' to enable research)"
        else:
            mode = f"research ({llm_cfg.provider}/{llm_cfg.get_model()})"
            should_train = True

    _print_banner(node, port, config.peer, mode, resource, config.task_id or "auto")

    async def _run():
        import uvicorn

        from .explorer import create_app

        shutdown = asyncio.Event()
        restart_requested = asyncio.Event()
        explorer_task: asyncio.Task | None = None
        loop_task: asyncio.Task | None = None
        operator_task: asyncio.Task | None = None
        server: uvicorn.Server | None = None

        def _request_shutdown():
            shutdown.set()

        event_loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                event_loop.add_signal_handler(sig, _request_shutdown)
            except NotImplementedError:
                pass

        # Start peer connections immediately
        await node.start(skip_peer=genesis)

        # For non-genesis nodes, run data prep concurrently with peer sync
        if (should_train or should_verify) and not genesis:
            prepare_task = asyncio.create_task(asyncio.to_thread(_prepare_data_only))
        else:
            prepare_task = None

        # Start explorer web UI (non-fatal if it fails)
        actual_web_port = _find_available_port(web_port)
        if actual_web_port:
            try:
                app = create_app(node, enable_cache=config.enable_cache)
                uvi_config = uvicorn.Config(
                    app, host="0.0.0.0", port=actual_web_port, log_level="warning"
                )
                server = uvicorn.Server(uvi_config)

                async def _run_explorer():
                    while not shutdown.is_set():
                        try:
                            await server.serve()
                            break
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            if shutdown.is_set():
                                break
                            log.warning("Explorer crashed: %s — restarting in 5s", exc)
                            console.print(
                                f"  [dim]Explorer crashed: {exc} — restarting...[/]"
                            )
                            await asyncio.sleep(5)
                            server.started = False

                explorer_task = asyncio.create_task(_run_explorer())
                # Give uvicorn a moment to bind
                await asyncio.sleep(0.5)
                if server.started:
                    if actual_web_port != web_port:
                        console.print(
                            f"  [dim]Explorer port {web_port} was busy, using :{actual_web_port}[/]"
                        )
                    console.print(
                        f"  Explorer: [link=http://localhost:{actual_web_port}]http://localhost:{actual_web_port}[/link]"
                    )
                else:
                    console.print(
                        f"  [dim]Explorer failed to bind on :{actual_web_port}[/]"
                    )
            except Exception as exc:
                console.print(f"  [dim]Explorer failed: {exc}[/]")
        else:
            console.print("  [dim]No port available for explorer (non-fatal)[/]")
        console.print()

        try:
            can_train = should_train
            can_verify = should_verify
            if (can_train or can_verify) and prepare_task:
                try:
                    await prepare_task
                except Exception as e:
                    console.print(f"[red]Data preparation failed: {e}[/]")
                    can_train = False
                    can_verify = False

            if can_verify:
                node.workspace = Path.cwd()

            if can_train:
                from .loop import ExperimentLoop

                loop = ExperimentLoop(node, Path.cwd())
                loop_task = asyncio.create_task(loop.run())
            try:
                current_version = importlib.metadata.version("sporemesh")
            except importlib.metadata.PackageNotFoundError:
                from . import __version__ as current_version

            operator = AutoOperator(
                manifest_url=config.update_manifest_url,
                current_version=current_version,
                interval_sec=config.update_interval_sec,
                enabled=config.auto_update,
                workdir=Path.cwd(),
            )

            async def _on_update(_version: str):
                console.print("  [dim]Auto-update applied. Restarting node...[/]")
                restart_requested.set()
                shutdown.set()

            if config.auto_update:
                operator_task = asyncio.create_task(operator.run_loop(_on_update))
            await shutdown.wait()
            return restart_requested.is_set()
        except asyncio.CancelledError:
            return False
        finally:
            shutdown.set()
            if operator_task:
                operator_task.cancel()
                try:
                    await operator_task
                except asyncio.CancelledError:
                    pass
            if loop_task:
                loop_task.cancel()
                try:
                    await loop_task
                except asyncio.CancelledError:
                    pass
            if server:
                server.should_exit = True
            if explorer_task:
                explorer_task.cancel()
                try:
                    await explorer_task
                except asyncio.CancelledError:
                    pass
            await node.stop()

    restart = False
    try:
        restart = asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\nShutting down.")
    except OSError as e:
        _handle_port_error(e, port)
    if restart:
        os.execv(sys.executable, [sys.executable, "-m", "spore.cli", *sys.argv[1:]])


@cli.command()
@click.argument("addr")
def connect(addr: str):
    """Add a peer to the config (host:port)."""
    ensure_initialized()
    config = NodeConfig.load()
    if addr in config.peer:
        console.print(f"Peer [cyan]{addr}[/] already configured.")
        return
    config.peer.append(addr)
    config.save()
    console.print(f"Added peer [cyan]{addr}[/].")


@cli.command()
@click.argument("addr")
def disconnect(addr: str):
    """Remove a peer from the config."""
    ensure_initialized()
    config = NodeConfig.load()
    if addr not in config.peer:
        console.print(f"Peer [cyan]{addr}[/] not found in config.")
        return
    config.peer.remove(addr)
    config.save()
    console.print(f"Removed peer [cyan]{addr}[/].")


@cli.command(name="peer")
def list_peer():
    """List configured and discovered peers."""
    ensure_initialized()
    config = NodeConfig.load()
    known_path = Path(config.data_dir).expanduser() / "known_peer"
    known = set()
    if known_path.exists():
        known = {l.strip() for l in known_path.read_text().splitlines() if l.strip()}

    if not config.peer and not known:
        console.print("No peers. Use [cyan]spore connect <host:port>[/] to add.")
        return

    if config.peer:
        console.print("[bold]Configured[/]")
        for p in config.peer:
            console.print(f"  - {p}")
    discovered = known - set(config.peer)
    if discovered:
        console.print("[bold]Discovered (via PEX)[/]")
        for p in sorted(discovered):
            console.print(f"  - [dim]{p}[/]")


@cli.group()
def profile():
    """Manage signed node profile metadata."""
    pass


@profile.command("show")
@click.option(
    "--data-dir", "-d", default=None, help="Data directory (default: ~/.spore)"
)
def profile_show(data_dir: str | None):
    """Show the current local node profile."""
    data_path = Path(data_dir).expanduser() if data_dir else SPORE_DIR
    ensure_initialized(data_path)
    node = SporeNode(NodeConfig.load(data_path / "config.toml"))
    current = node.get_profile(node.node_id)
    if current is None:
        console.print("No local profile set.")
    else:
        console.print(f"Node: [cyan]{node.node_id[:16]}...[/]")
        console.print(f"Display name: {current.display_name or '—'}")
        console.print(f"Bio: {current.bio or '—'}")
        console.print(f"Website: {current.website or '—'}")
        console.print(f"Avatar URL: {current.avatar_url or '—'}")
        console.print(f"Donation address: {current.donation_address or '—'}")
    node.graph.close()
    node.profile.close()
    node.reputation.close()


@profile.command("set")
@click.option("--display-name", required=True, help="Public display name")
@click.option("--bio", default="", help="Short profile description")
@click.option("--website", default="", help="Public website URL")
@click.option("--avatar-url", default="", help="Avatar image URL")
@click.option("--donation-address", default="", help="Optional donation address")
@click.option(
    "--data-dir", "-d", default=None, help="Data directory (default: ~/.spore)"
)
def profile_set(
    display_name: str,
    bio: str,
    website: str,
    avatar_url: str,
    donation_address: str,
    data_dir: str | None,
):
    """Set the local signed node profile."""
    data_path = Path(data_dir).expanduser() if data_dir else SPORE_DIR
    ensure_initialized(data_path)
    config = NodeConfig.load(data_path / "config.toml")
    config.data_dir = str(data_path)
    node = SporeNode(config)
    profile = node.update_local_profile(
        display_name=display_name,
        bio=bio,
        website=website,
        avatar_url=avatar_url,
        donation_address=donation_address,
    )
    console.print(f"Saved profile for [cyan]{node.node_id[:16]}...[/]")
    console.print(f"Display name: {profile.display_name}")
    console.print("Profile will gossip on next `spore run` or `spore explorer`.")
    node.graph.close()
    node.profile.close()
    node.reputation.close()


@cli.command()
@click.option("--port", "-p", default=7470, help="Gossip port")
@click.option("--web-port", "-w", default=8470, help="Web UI port")
@click.option("--peer", "-c", multiple=True, help="Peer address (host:port)")
@click.option("--task", "task_id", default="", help="Task ID to display by default")
def explorer(port: int, web_port: int, peer: tuple[str, ...], task_id: str):
    """Launch the Spore Explorer web UI with a gossip server.

    If a daemon is already running, the explorer auto-attaches to it
    and serves the web UI in view mode.
    """
    import uvicorn

    from .daemon import is_running
    from .explorer import create_app

    ensure_initialized()
    config = NodeConfig.load()
    config.port = port
    if peer:
        config.peer = list(peer)
    if task_id:
        config.task_id = task_id

    # Find an available web port
    actual_web_port = _find_available_port(web_port)
    if actual_web_port is None:
        console.print(f"[red]No available port found near {web_port}.[/]")
        return

    node = SporeNode(config)
    app = create_app(node)

    console.print("\n[bold]Spore Explorer[/]")
    console.print(f"  Node:   [cyan]{node.node_id[:16]}...[/]")
    url = f"http://localhost:{actual_web_port}"
    console.print(f"  Web UI: [link={url}]{url}[/link]")

    async def _run():
        try:
            await node.start()
            console.print(f"  Gossip: {config.host}:{port}")
        except OSError as e:
            if "address already in use" not in str(e).lower():
                raise
            node.gossip.port = 0
            await node.gossip.start()
            await node.gossip.connect_to_peer("127.0.0.1", port)
            daemon_pid = is_running()
            if daemon_pid:
                console.print(
                    f"  [dim]Attached to daemon (PID {daemon_pid}) on :{port}[/]"
                )
            else:
                console.print(f"  [dim]Attached to existing node on :{port}[/]")

        if config.peer:
            console.print(f"  Peer:   {', '.join(config.peer)}")
        console.print()

        uvi_config = uvicorn.Config(
            app, host="0.0.0.0", port=actual_web_port, log_level="warning"
        )
        server = uvicorn.Server(uvi_config)
        await server.serve()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\nShutting down.")
    except OSError as e:
        _handle_port_error(e, actual_web_port)


@cli.command()
@click.option(
    "--all",
    "clean_all",
    is_flag=True,
    help="Also remove cached data (~/.cache/autoresearch)",
)
@click.option(
    "--workspace",
    is_flag=True,
    help="Also remove train.py/prepare.py from current directory",
)
def clean(clean_all: bool, workspace: bool):
    """Remove all Spore data (identity, database, config, artifact, log).

    By default removes ~/.spore/. Use --all to also remove cached training
    data (~/.cache/autoresearch). Use --workspace to remove train.py and
    prepare.py from the current directory.
    """
    import shutil

    targets: list[tuple[Path, str]] = [
        (SPORE_DIR, "~/.spore (identity, database, config)"),
    ]
    if clean_all:
        targets.append(
            (
                Path("~/.cache/autoresearch").expanduser(),
                "~/.cache/autoresearch (training data)",
            )
        )
    if workspace:
        for f in ("train.py", "prepare.py", "run.log"):
            p = Path.cwd() / f
            if p.exists():
                targets.append((p, f"{f} (workspace file)"))

    existing = [(p, desc) for p, desc in targets if p.exists()]
    if not existing:
        console.print("Nothing to clean.")
        return

    console.print("[bold]This will delete:[/]")
    for _, desc in existing:
        console.print(f"  [red]- {desc}[/]")

    if not click.confirm("\nContinue?"):
        console.print("Aborted.")
        return

    for p, desc in existing:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        console.print(f"  Removed {desc}")

    console.print("[green]Clean.[/]")


@cli.command()
def version():
    """Show the Spore version."""
    try:
        ver = importlib.metadata.version("sporemesh")
    except importlib.metadata.PackageNotFoundError:
        from . import __version__ as ver
    console.print(f"spore [cyan]{ver}[/]")


# --- Helpers ---


def _copy_workspace_file():
    """Copy bundled workspace files to cwd without running prepare.py."""
    import shutil
    from importlib.resources import files

    workspace_pkg = files("spore.workspace")
    for filename in ("train.py", "prepare.py", "batching.py"):
        dest = Path.cwd() / filename
        if not dest.exists():
            src = workspace_pkg / filename
            shutil.copy2(str(src), str(dest))
            console.print(f"  Copied [cyan]{filename}[/] to working directory.")


def _data_is_ready() -> bool:
    """Check if training data and tokenizer are fully prepared."""
    cache_dir = Path("~/.cache/autoresearch").expanduser()
    tokenizer = cache_dir / "tokenizer" / "tokenizer.pkl"
    data_dir = cache_dir / "data"
    return tokenizer.exists() and data_dir.exists() and any(data_dir.iterdir())


def _prepare_data_only():
    """Run prepare.py if data isn't ready. Safe to call from a thread."""
    import subprocess

    if _data_is_ready():
        console.print("[dim]Data already prepared, skipping.[/]")
        return

    console.print("[bold]Preparing data (this may download ~GB of data)...[/]")
    result = subprocess.run(
        [sys.executable, "prepare.py"],
        cwd=str(Path.cwd()),
    )
    if result.returncode != 0:
        raise RuntimeError("prepare.py failed")
    console.print("[green]Data prepared.[/]")


def _auto_prepare():
    """Copy bundled workspace files and run prepare.py if data is missing."""
    _copy_workspace_file()
    _prepare_data_only()


def _configure_logging():
    """Set up logging to both console and file."""
    log_dir = SPORE_DIR / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "spore.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler — minimal format for user
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("  %(message)s"))
    root.addHandler(console_handler)

    # File handler — full detail for diagnostics
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=3
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(file_handler)

    # Quiet down noisy loggers
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def _print_banner(
    node: SporeNode,
    port: int,
    peer: list[str],
    mode: str,
    resource: int = 100,
    task_id: str = "auto",
):
    from rich.panel import Panel
    from rich.table import Table

    try:
        ver = importlib.metadata.version("sporemesh")
    except importlib.metadata.PackageNotFoundError:
        from . import __version__ as ver

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("Node", f"[cyan]{node.node_id[:16]}...[/]")
    grid.add_row("Port", str(port))
    grid.add_row("Peer", f"{len(peer)} configured")
    grid.add_row("Task", task_id if task_id == "auto" else f"{task_id[:16]}...")
    grid.add_row("Resource", f"{resource}%")
    grid.add_row("Mode", f"[bold]{mode}[/]")

    console.print()
    console.print(
        Panel(
            grid,
            title=f"[bold]Spore[/] [dim]v{ver}[/]",
            border_style="cyan",
            expand=False,
        )
    )
    console.print()


def _find_available_port(start: int, max_attempt: int = 10) -> int | None:
    """Find an available port starting from `start`, trying up to max_attempt."""
    import socket

    for offset in range(max_attempt):
        candidate = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", candidate))
                return candidate
            except OSError:
                continue
    return None


def _handle_port_error(e: OSError, port: int):
    if "address already in use" in str(e).lower():
        console.print(f"\n[red]Port {port} is already in use.[/]")
        console.print(f"  Try:  [cyan]spore run --port {port + 1}[/]")
        console.print("  Or:   [cyan]spore stop[/]  (if a daemon is running)")
    else:
        console.print(f"[red]Network error: {e}[/]")


# --- Register sub-module commands ---

from .daemon import register_command as _register_daemon
from .llm import register_command as _register_llm
from .query import register_command as _register_query
from .task_cli import register_command as _register_task

_register_query(cli)
_register_daemon(cli)
_register_llm(cli)
_register_task(cli)


def main():
    """Entry point with global error handling."""
    try:
        cli()
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        console.print("[dim]Run with SPORE_DEBUG=1 for full traceback.[/]")
        import os

        if os.environ.get("SPORE_DEBUG"):
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import importlib.metadata
import json
import socket
import uuid
import webbrowser
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from .client_api import BackendClient, ClientError
from .client_challenge import list_challenges
from .client_auth import login_with_private_key
from .client_detect import detect_node_profile
from .client_init import initialize_client
from .client_store import CONFIG_PATH, load_config, save_config, update_config

console = Console()


def _print(data: Any) -> None:
    console.print_json(json.dumps(data, default=str))


def _parse_json(text: str | None, file_path: str | None) -> dict[str, Any] | None:
    if text:
        return json.loads(text)
    if file_path:
        return json.loads(Path(file_path).read_text())
    return None


def _node_public_id(value: str | None) -> str:
    if value:
        return value
    hostname = socket.gethostname().split(".")[0]
    return f"{hostname}-{uuid.uuid4().hex[:8]}"


@click.group()
def cli() -> None:
    """Spore CLI for the centralized Spore backend."""


@cli.command()
@click.option("--private-key", envvar="SPORE_PRIVATE_KEY", required=True, help="Ethereum private key")
@click.option("--base-url", default=None, help="Override backend URL")
def login(private_key: str, base_url: str | None) -> None:
    """Authenticate with the backend and save an API key."""
    _print(login_with_private_key(private_key, base_url=base_url))


@cli.command()
@click.option("--private-key", envvar="SPORE_PRIVATE_KEY", default=None, help="Ethereum private key")
@click.option("--base-url", default=None, help="Override backend URL")
@click.option("--node-public-id", default=None, help="Stable public node ID")
@click.option("--label", default=None, help="Human-readable node label override")
@click.option("--challenge-id", default=None, help="Pin a default challenge instead of auto-selecting")
@click.option("--force-new-wallet", is_flag=True, help="Generate and save a fresh local wallet")
@click.option("--llm-provider", default="groq", help="LLM provider for local challenge runtime")
@click.option("--llm-api-key", envvar="SPORE_LLM_API_KEY", default=None, help="LLM API key for local challenge runtime")
@click.option("--llm-model", default=None, help="Optional LLM model override")
def init(
    private_key: str | None,
    base_url: str | None,
    node_public_id: str | None,
    label: str | None,
    challenge_id: str | None,
    force_new_wallet: bool,
    llm_provider: str,
    llm_api_key: str | None,
    llm_model: str | None,
) -> None:
    """Generate or reuse a wallet, register a node, and save a default challenge."""
    _print(
        initialize_client(
            private_key=private_key,
            base_url=base_url,
            node_public_id=_node_public_id(node_public_id),
            label=label,
            challenge_id=challenge_id,
            force_new_wallet=force_new_wallet,
            llm_provider=llm_provider,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
        )
    )


@cli.command()
def logout() -> None:
    """Clear the saved API key."""
    config = load_config()
    config["api_key"] = ""
    save_config(config)
    console.print(f"Cleared API key in {CONFIG_PATH}")


@cli.group()
def config() -> None:
    """Inspect or update local CLI config."""


@config.command("show")
def config_show() -> None:
    _print(load_config())


@config.command("set-base-url")
@click.argument("base_url")
def config_set_base_url(base_url: str) -> None:
    _print(update_config(base_url=base_url.rstrip("/")))


@cli.command("whoami")
def whoami() -> None:
    """Show the authenticated operator."""
    _print(BackendClient().get("/api/v1/operator/me", auth=True))


@cli.group()
def challenge() -> None:
    """Challenge queries."""


@challenge.command("list")
def challenge_list() -> None:
    _print(list_challenges())


@challenge.command("show")
@click.argument("challenge_id", required=False)
def challenge_show(challenge_id: str | None) -> None:
    challenge_id = challenge_id or load_config().get("default_challenge_id")
    if not challenge_id:
        raise click.ClickException("missing challenge_id; run `spore init` or pass a challenge id")
    _print(BackendClient().get(f"/api/v1/challenge/{challenge_id}"))


@challenge.command("leaderboard")
@click.argument("challenge_id", required=False)
def challenge_leaderboard(challenge_id: str | None) -> None:
    challenge_id = challenge_id or load_config().get("default_challenge_id")
    if not challenge_id:
        raise click.ClickException("missing challenge_id; run `spore init` or pass a challenge id")
    _print(BackendClient().get(f"/api/v1/challenge/{challenge_id}/leaderboard"))


@challenge.command("payout-preview")
@click.argument("challenge_id", required=False)
def challenge_payout_preview(challenge_id: str | None) -> None:
    challenge_id = challenge_id or load_config().get("default_challenge_id")
    if not challenge_id:
        raise click.ClickException("missing challenge_id; run `spore init` or pass a challenge id")
    _print(BackendClient().get(f"/api/v1/challenge/{challenge_id}/payout-preview", auth=True))


@challenge.command("use")
@click.argument("challenge_id")
def challenge_use(challenge_id: str) -> None:
    challenge = BackendClient().get(f"/api/v1/challenge/{challenge_id}")
    _print(update_config(default_challenge_id=challenge["id"], default_challenge_slug=challenge.get("slug", "")))


@cli.command("play")
@click.option("--challenge-id", default=None, help="Open the browser arena for a specific challenge")
@click.option("--open", "should_open", is_flag=True, help="Open the arena URL in your default browser")
def play(challenge_id: str | None, should_open: bool) -> None:
    """Open the browser arena for a browser-capable challenge."""
    config = load_config()
    target = challenge_id or config.get("default_challenge_id")
    url = "https://www.sporemesh.com/play"
    if target:
        url = f"{url}?challenge_id={target}"
    if should_open:
        webbrowser.open(url)
    console.print(url)


@cli.group()
def node() -> None:
    """Node registration and heartbeat."""


@node.command("register")
@click.option("--node-public-id", default=None, help="Stable public node ID")
@click.option("--label", default="", help="Human-readable node label")
@click.option("--gpu-model", default="", help="Reported GPU model")
@click.option("--cpu-model", default="", help="Reported CPU model")
@click.option("--memory-gb", type=int, default=None, help="Reported memory in GB")
@click.option("--platform", default="", help="OS/platform label")
@click.option("--software-version", default="", help="Client version")
@click.option("--metadata", default=None, help="Inline JSON metadata")
@click.option("--metadata-file", default=None, help="Path to metadata JSON")
def node_register(
    node_public_id: str | None,
    label: str,
    gpu_model: str,
    cpu_model: str,
    memory_gb: int | None,
    platform: str,
    software_version: str,
    metadata: str | None,
    metadata_file: str | None,
) -> None:
    detected = detect_node_profile()
    node_public_id = _node_public_id(node_public_id)
    payload = {
        "node_public_id": node_public_id,
        "label": label or detected["label"],
        "gpu_model": gpu_model or detected["gpu_model"] or None,
        "cpu_model": cpu_model or detected["cpu_model"] or None,
        "memory_gb": memory_gb or detected["memory_gb"],
        "platform": platform or detected["platform"] or None,
        "software_version": software_version or current_version(),
        "metadata_jsonb": _parse_json(metadata, metadata_file) or detected["metadata_jsonb"],
    }
    result = BackendClient().post("/api/v1/node/register", auth=True, json_body=payload)
    update_config(default_node_id=result.get("id", ""), default_node_public_id=node_public_id)
    _print(result)


@node.command("heartbeat")
@click.option("--node-public-id", default=None, help="Stable public node ID")
@click.option("--metadata", default=None, help="Inline JSON metadata")
@click.option("--metadata-file", default=None, help="Path to metadata JSON")
def node_heartbeat(
    node_public_id: str | None,
    metadata: str | None,
    metadata_file: str | None,
) -> None:
    config = load_config()
    payload = {
        "node_public_id": node_public_id or config.get("default_node_public_id") or _node_public_id(None),
        "metadata_jsonb": _parse_json(metadata, metadata_file),
    }
    _print(BackendClient().post("/api/v1/node/heartbeat", auth=True, json_body=payload))


@node.command("me")
def node_me() -> None:
    _print(BackendClient().get("/api/v1/node/me", auth=True))


@cli.group()
def submission() -> None:
    """Submission commands."""


@submission.command("create")
@click.option("--challenge-id", default=None)
@click.option("--node-id", default=None, help="Backend node ID; defaults to saved node")
@click.option("--parent-submission-id", default=None)
@click.option("--status", type=click.Choice(["keep", "discard", "crash"]), required=True)
@click.option("--metric-value", type=float, default=None)
@click.option("--title", default="")
@click.option("--hypothesis", default="")
@click.option("--description", default="")
@click.option("--diff-summary", default="")
@click.option("--runtime-sec", type=int, default=None)
@click.option("--peak-vram-mb", type=float, default=None)
@click.option("--num-steps", type=int, default=None)
@click.option("--num-params", type=int, default=None)
@click.option("--agent-model", default="")
@click.option("--gpu-model", default="")
@click.option("--metadata", default=None)
@click.option("--metadata-file", default=None)
def submission_create(**kwargs: Any) -> None:
    config = load_config()
    kwargs["challenge_id"] = kwargs["challenge_id"] or config.get("default_challenge_id")
    kwargs["node_id"] = kwargs["node_id"] or config.get("default_node_id")
    kwargs["metadata_jsonb"] = _parse_json(kwargs.pop("metadata"), kwargs.pop("metadata_file"))
    if not kwargs["challenge_id"]:
        raise click.ClickException("missing challenge_id; run `spore init` or pass --challenge-id")
    if not kwargs["node_id"]:
        raise click.ClickException("missing node_id; run `spore init` or `spore node register` first")
    _print(BackendClient().post("/api/v1/submission", auth=True, json_body=kwargs))


@submission.command("list")
@click.argument("challenge_id", required=False)
def submission_list(challenge_id: str | None) -> None:
    challenge_id = challenge_id or load_config().get("default_challenge_id")
    if not challenge_id:
        raise click.ClickException("missing challenge_id; run `spore init` or pass a challenge id")
    _print(BackendClient().get(f"/api/v1/challenge/{challenge_id}/submission", auth=True))


@submission.command("show")
@click.argument("submission_id")
def submission_show(submission_id: str) -> None:
    _print(BackendClient().get(f"/api/v1/submission/{submission_id}", auth=True))


@submission.command("lineage")
@click.argument("challenge_id")
@click.argument("submission_id")
def submission_lineage(challenge_id: str, submission_id: str) -> None:
    _print(
        BackendClient().get(
            f"/api/v1/challenge/{challenge_id}/submission/{submission_id}/lineage",
            auth=True,
        )
    )


@cli.group()
def artifact() -> None:
    """Artifact metadata commands."""


@artifact.command("create")
@click.option("--submission-id", required=True)
@click.option("--kind", required=True)
@click.option("--filename", required=True)
@click.option("--content-type", default=None)
@click.option("--size-bytes", type=int, default=None)
@click.option("--metadata", default=None)
@click.option("--metadata-file", default=None)
def artifact_create(**kwargs: Any) -> None:
    kwargs["metadata_jsonb"] = _parse_json(kwargs.pop("metadata"), kwargs.pop("metadata_file"))
    _print(BackendClient().post("/api/v1/artifact", auth=True, json_body=kwargs))


@artifact.command("list")
@click.argument("submission_id")
def artifact_list(submission_id: str) -> None:
    _print(BackendClient().get(f"/api/v1/submission/{submission_id}/artifact", auth=True))


@cli.group()
def payout() -> None:
    """Payout queries."""


@payout.command("me")
def payout_me() -> None:
    _print(BackendClient().get("/api/v1/operator/me/payout", auth=True))


@payout.command("challenge")
@click.argument("challenge_id")
def payout_challenge(challenge_id: str) -> None:
    _print(BackendClient().get(f"/api/v1/challenge/{challenge_id}/payout", auth=True))


def current_version() -> str:
    try:
        return importlib.metadata.version("sporemesh")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def main() -> None:
    try:
        cli()
    except ClientError as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()

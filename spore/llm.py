"""LLM integration — provider-agnostic AI client for experiment proposal.

Supports Anthropic, OpenAI, Groq, xAI (Grok), and any OpenAI-compatible endpoint.
All providers use the OpenAI chat completions format via raw HTTP (no SDK needed).

Configure with: spore set <provider> <api_key>
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests
import tomllib

log = logging.getLogger(__name__)

# Provider registry: name -> (base_url, default_model, display_name)
PROVIDER = {
    "anthropic": (
        "https://api.anthropic.com/v1",
        "claude-sonnet-4-5-20250929",
        "Anthropic",
    ),
    "openai": ("https://api.openai.com/v1", "gpt-4o", "OpenAI"),
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "Groq"),
    "xai": ("https://api.x.ai/v1", "grok-3", "xAI"),
}

LLM_CONFIG_FILE = "llm.toml"


@dataclass
class LLMConfig:
    provider: str = ""
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    max_token: int = 16384
    temperature: float = 0.7

    def is_configured(self) -> bool:
        return bool(self.api_key and (self.provider in PROVIDER or self.base_url))

    def get_base_url(self) -> str:
        if self.base_url:
            return self.base_url
        if self.provider in PROVIDER:
            return PROVIDER[self.provider][0]
        raise ValueError(f"Unknown provider: {self.provider!r}")

    def get_model(self) -> str:
        if self.model:
            return self.model
        if self.provider in PROVIDER:
            return PROVIDER[self.provider][1]
        raise ValueError("No model configured")


class LLMClient:
    """Provider-agnostic LLM client. One POST to /chat/completions."""

    def __init__(self, config: LLMConfig):
        if not config.is_configured():
            raise ValueError("LLM not configured. Run: spore set <provider> <api_key>")
        self.config = config
        self.base_url = config.get_base_url().rstrip("/")
        self.model = config.get_model()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            }
        )

    def chat(self, system: str, user: str) -> str:
        """Send a chat completion request. Returns the assistant's response text."""
        log.info("LLM request: %s %s", self.config.provider, self.model)

        if self.config.provider == "anthropic":
            return self._chat_anthropic(system, user)
        return self._chat_openai(system, user)

    def _chat_openai(self, system: str, user: str) -> str:
        """OpenAI-compatible chat completions (OpenAI, Groq, xAI, custom)."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "max_tokens": self.config.max_token,
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        resp = self._post_with_retry(url, payload)
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        log.info(
            "LLM response: %d prompt + %d completion tokens",
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )
        return content

    def _chat_anthropic(self, system: str, user: str) -> str:
        """Native Anthropic Messages API."""
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": self.config.max_token,
            "temperature": self.config.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        resp = self._post_with_retry(url, payload, headers=headers, session=None)
        resp.raise_for_status()
        data = resp.json()

        content = "".join(
            block["text"] for block in data["content"] if block["type"] == "text"
        )
        usage = data.get("usage", {})
        log.info(
            "LLM response: %d prompt + %d completion tokens",
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )
        return content

    def _post_with_retry(
        self,
        url: str,
        payload: dict,
        *,
        headers: dict | None = None,
        session: requests.Session | None = None,
        timeout: int = 120,
        max_attempts: int = 3,
    ):
        client = session or self.session
        delay = 1.0
        for attempt in range(1, max_attempts + 1):
            try:
                return client.post(url, json=payload, headers=headers, timeout=timeout)
            except requests.exceptions.RequestException as exc:
                if attempt >= max_attempts:
                    raise
                log.warning(
                    "LLM request failed (%s/%s): %s",
                    attempt,
                    max_attempts,
                    exc,
                )
                time.sleep(delay)
                delay *= 2


# ---------------------------------------------------------------------------
# Config persistence (stored in ~/.spore/llm.toml)
# ---------------------------------------------------------------------------


def load_config(data_dir: Path) -> LLMConfig:
    """Load LLM config from data_dir/llm.toml."""
    path = data_dir / LLM_CONFIG_FILE
    if not path.exists():
        return LLMConfig()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return LLMConfig(
        provider=data.get("provider", ""),
        api_key=data.get("api_key", ""),
        model=data.get("model", ""),
        base_url=data.get("base_url", ""),
        max_token=data.get("max_token", 16384),
        temperature=data.get("temperature", 0.7),
    )


def save_config(data_dir: Path, config: LLMConfig):
    """Save LLM config to data_dir/llm.toml."""
    path = data_dir / LLM_CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'provider = "{config.provider}"',
        f'api_key = "{config.api_key}"',
        f'model = "{config.get_model()}"',
    ]
    if config.base_url:
        lines.append(f'base_url = "{config.base_url}"')
    if config.max_token != 16384:
        lines.append(f"max_token = {config.max_token}")
    if config.temperature != 0.7:
        lines.append(f"temperature = {config.temperature}")
    path.write_text("\n".join(lines) + "\n")


def make_client(data_dir: Path) -> LLMClient:
    """Load config and create an LLMClient. Raises ValueError if not configured."""
    return LLMClient(load_config(data_dir))


# ---------------------------------------------------------------------------
# CLI: spore set
# ---------------------------------------------------------------------------


def register_command(cli):
    """Register the 'set' command on the CLI group."""
    import click
    from rich.console import Console
    from rich.table import Table

    from .node import SPORE_DIR

    console = Console()

    @cli.command(name="set")
    @click.argument("provider", required=False)
    @click.argument("api_key", required=False)
    @click.option(
        "--model",
        "-m",
        default=None,
        help="Model override (defaults to best for provider)",
    )
    @click.option(
        "--base-url", default=None, help="Endpoint URL (required for 'custom' provider)"
    )
    def set_llm(
        provider: str | None,
        api_key: str | None,
        model: str | None,
        base_url: str | None,
    ):
        """Configure the LLM for autonomous research.

        \b
        Examples:
          spore set groq gsk_xxxxx
          spore set anthropic sk-ant-xxxxx
          spore set openai sk-xxxxx --model gpt-4o
          spore set xai xai-xxxxx
          spore set custom sk-xxx --base-url http://localhost:8080/v1
          spore set                            # show current config
        """
        from .cli import ensure_initialized

        ensure_initialized()

        if not provider:
            _show_config(console, SPORE_DIR)
            return

        if not api_key:
            console.print(
                f"[red]API key required.[/]  Usage: [cyan]spore set {provider} <api_key>[/]"
            )
            return

        if provider == "custom" and not base_url:
            console.print("[red]Custom provider requires --base-url.[/]")
            console.print("  [cyan]spore set custom <key> --base-url http://...[/]")
            return

        if provider not in PROVIDER and provider != "custom":
            console.print(f"[red]Unknown provider: {provider}[/]")
            console.print(f"  Available: [cyan]{', '.join(PROVIDER.keys())}[/], custom")
            return

        config = LLMConfig(
            provider=provider,
            api_key=api_key,
            model=model or "",
            base_url=base_url or "",
        )
        save_config(SPORE_DIR, config)

        display_model = config.get_model()
        masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "****"
        console.print(f"LLM configured: [cyan]{provider}[/] / [cyan]{display_model}[/]")
        console.print(f"  Key: [dim]{masked_key}[/]")

    def _show_config(console: Console, data_dir: Path):
        config = load_config(data_dir)
        if not config.is_configured():
            table = Table(title="Available Provider", show_header=True)
            table.add_column("Name", style="cyan")
            table.add_column("Default Model")
            for name, (_, default_model, display) in PROVIDER.items():
                table.add_row(name, default_model)
            table.add_row("custom", "(any OpenAI-compatible endpoint)")
            console.print(table)
            console.print("\nUsage: [cyan]spore set <provider> <api_key>[/]")
            return

        console.print("[bold]LLM Config[/]")
        display = PROVIDER.get(config.provider, ("", "", config.provider))[2]
        console.print(f"  Provider:  [cyan]{display}[/] ({config.provider})")
        console.print(f"  Model:     [cyan]{config.get_model()}[/]")
        masked = (
            f"{config.api_key[:8]}...{config.api_key[-4:]}"
            if len(config.api_key) > 12
            else "****"
        )
        console.print(f"  Key:       [dim]{masked}[/]")
        if config.base_url:
            console.print(f"  Endpoint:  {config.base_url}")

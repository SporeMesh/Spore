"""Auto-operator for release manifest checks and safe self-updates."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

log = logging.getLogger(__name__)


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for chunk in value.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits or "0"))
    return tuple(parts)


@dataclass
class ReleaseManifest:
    version: str
    pip_spec: str = ""
    wheel_url: str = ""
    instructions: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_json(cls, payload: str | bytes | dict) -> "ReleaseManifest":
        if isinstance(payload, (str, bytes)):
            payload = json.loads(payload)
        return cls(**dict(payload))


class AutoOperator:
    """Periodically checks the official release manifest and applies updates."""

    def __init__(
        self,
        *,
        manifest_url: str,
        current_version: str,
        interval_sec: int = 21600,
        enabled: bool = True,
        workdir: Path | None = None,
    ):
        self.manifest_url = manifest_url
        self.current_version = current_version
        self.interval_sec = max(300, interval_sec)
        self.enabled = enabled
        self.workdir = workdir or Path.cwd()

    def is_newer(self, version: str) -> bool:
        return _version_tuple(version) > _version_tuple(self.current_version)

    def fetch_manifest(self) -> ReleaseManifest | None:
        if not self.enabled:
            return None
        with urllib.request.urlopen(self.manifest_url, timeout=20) as response:
            return ReleaseManifest.from_json(response.read().decode("utf-8"))

    def apply_update(self, manifest: ReleaseManifest) -> bool:
        if not self.is_newer(manifest.version):
            return False
        target = (
            manifest.pip_spec or manifest.wheel_url or f"sporemesh=={manifest.version}"
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", target],
            check=True,
        )
        for instruction in manifest.instructions:
            self.apply_instruction(instruction)
        self.current_version = manifest.version
        return True

    def apply_instruction(self, instruction: str):
        if instruction == "copy_workspace":
            workspace_pkg = files("spore.workspace")
            for filename in ("train.py", "prepare.py", "batching.py"):
                shutil.copy2(
                    str(workspace_pkg / filename),
                    str(self.workdir / filename),
                )
            return
        if instruction == "backfill_tasks":
            return
        raise ValueError(f"Unsupported update instruction: {instruction}")

    async def run_loop(self, on_update_applied):
        if not self.enabled:
            return
        while True:
            try:
                manifest = await asyncio.to_thread(self.fetch_manifest)
                if manifest and self.is_newer(manifest.version):
                    log.info(
                        "Applying update %s from release manifest", manifest.version
                    )
                    updated = await asyncio.to_thread(self.apply_update, manifest)
                    if updated:
                        await on_update_applied(manifest.version)
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Auto-update check failed: %s", exc)
            await asyncio.sleep(self.interval_sec)

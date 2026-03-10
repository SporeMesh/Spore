"""Serialization and workspace isolation for local training jobs."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from .runner import ExperimentRunner, TrainResult


class TrainingRuntime:
    """Run local training jobs without overlapping GPU workloads."""

    def __init__(self):
        self._lock = asyncio.Lock()

    async def run_runner(self, runner: ExperimentRunner) -> TrainResult:
        """Run a workspace-bound runner while holding the local training lock."""
        async with self._lock:
            return await asyncio.to_thread(runner.run_training)

    async def run_isolated(self, workspace: str | Path, train_code: str) -> TrainResult:
        """Run code in a temporary copy of the workspace under the same lock."""
        workspace_path = Path(workspace)
        with tempfile.TemporaryDirectory(prefix="spore-verify-") as tmpdir:
            tmp_path = Path(tmpdir)
            self._copy_workspace(workspace_path, tmp_path)
            (tmp_path / "train.py").write_text(train_code)
            runner = ExperimentRunner(tmp_path)
            async with self._lock:
                return await asyncio.to_thread(runner.run_training)

    def busy(self) -> bool:
        """Return whether a local training job is already running."""
        return self._lock.locked()

    def _copy_workspace(self, src: Path, dst: Path):
        for entry in src.iterdir():
            if entry.is_file() and entry.suffix == ".py":
                shutil.copy2(entry, dst / entry.name)

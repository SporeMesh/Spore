"""Tests for serialized local training runtime."""

from __future__ import annotations

import asyncio

import pytest

from spore.training_runtime import TrainingRuntime


@pytest.mark.asyncio
async def test_run_isolated_preserves_workspace_train_file(tmp_path):
    runtime = TrainingRuntime()
    (tmp_path / "prepare.py").write_text("VALUE = 1\n")
    (tmp_path / "train.py").write_text("print('original')\n")

    result = await runtime.run_isolated(
        tmp_path,
        "from prepare import VALUE\nprint('step 1')\nprint('num_parameters: 10')\nprint('peak_vram_mb: 1')\nprint('val_bpb: 1.23')\n",
    )

    assert result.success
    assert (tmp_path / "train.py").read_text() == "print('original')\n"


@pytest.mark.asyncio
async def test_runtime_serializes_overlapping_runs():
    runtime = TrainingRuntime()
    events: list[str] = []

    class FakeRunner:
        def run_training(self):
            events.append("start")
            import time

            time.sleep(0.05)
            events.append("end")
            from spore.runner import TrainResult

            return TrainResult(val_bpb=1.0, success=True)

    runner = FakeRunner()
    await asyncio.gather(runtime.run_runner(runner), runtime.run_runner(runner))

    assert events == ["start", "end", "start", "end"]

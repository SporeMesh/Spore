"""Tests for experiment loop behavior and metadata extraction."""

import asyncio
from types import SimpleNamespace

import pytest

from spore.loop import (
    ExperimentLoop,
    _extract_metadata,
    _is_valid_full_python_file,
)


@pytest.mark.asyncio
async def test_apply_frontier_code_waits_for_delayed_peer_discovery(monkeypatch):
    applied: list[str] = []
    loop = ExperimentLoop.__new__(ExperimentLoop)
    best = SimpleNamespace(
        id="abc12345" * 8, code_cid="codecid", val_bpb=1.1, task_id="task-1"
    )
    loop.node = SimpleNamespace(
        graph=SimpleNamespace(best_by_task=lambda task_id: best),
        store=SimpleNamespace(get=lambda cid: None),
        gossip=SimpleNamespace(peers={"bootstrap:7470": object()}),
        fetch_code=None,
        active_task_id="task-1",
    )
    loop.runner = SimpleNamespace(apply_code=lambda code: applied.append(code))

    attempts = {"count": 0}

    async def fake_fetch_code(code_cid: str):
        attempts["count"] += 1
        if attempts["count"] == 1:
            loop.node.gossip.peers["artifact:7470"] = object()
            return None
        return b"print('frontier')\n"

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(loop.node, "fetch_code", fake_fetch_code)
    monkeypatch.setattr("spore.loop.asyncio.sleep", fake_sleep)

    applied_ok = await loop._apply_frontier_code()

    assert applied_ok is True
    assert applied == ["print('frontier')\n"]
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_run_retries_frontier_fetch_without_running_baseline(monkeypatch):
    loop = ExperimentLoop.__new__(ExperimentLoop)
    state = {"attempts": 0, "baseline_called": False, "run_one_called": False}
    loop.node = SimpleNamespace(
        graph=SimpleNamespace(count=lambda: 5),
        config=SimpleNamespace(task_id="task-1"),
        active_task_id="task-1",
    )

    async def fake_await_peer_sync():
        return None

    async def fake_apply_frontier_code():
        state["attempts"] += 1
        return state["attempts"] >= 2

    async def fake_run_baseline():
        state["baseline_called"] = True
        return True

    async def fake_run_one():
        state["run_one_called"] = True
        raise asyncio.CancelledError

    async def fake_sleep(_seconds: float):
        return None

    loop._await_peer_sync = fake_await_peer_sync
    loop._apply_frontier_code = fake_apply_frontier_code
    loop._run_baseline = fake_run_baseline
    loop._run_one = fake_run_one

    monkeypatch.setattr("spore.loop.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await loop.run()

    assert state["attempts"] == 2
    assert state["baseline_called"] is False
    assert state["run_one_called"] is True


class TestExtractMetadata:
    def test_extract_structured_metadata(self):
        response = """
Description: Increase the embedding LR from 0.6 to 0.8.
Hypothesis: A slightly faster embedding update should improve adaptation inside the time budget.

```python
print("hello")
```
"""
        description, hypothesis = _extract_metadata(response)
        assert description == "Increase the embedding LR from 0.6 to 0.8."
        assert hypothesis == (
            "A slightly faster embedding update should improve adaptation inside the time budget."
        )

    def test_extract_legacy_single_line_metadata(self):
        response = """
I increased the embedding LR from 0.6 to 0.8 because faster token adaptation should lower val_bpb.

```python
print("hello")
```
"""
        description, hypothesis = _extract_metadata(response)
        assert description == "I increased the embedding LR from 0.6 to 0.8"
        assert hypothesis == "faster token adaptation should lower val_bpb"


class TestCandidateCodeValidation:
    def test_accepts_full_python_file(self):
        body = "\n".join(f"x_{i} = {i}" for i in range(220))
        code = (
            "from prepare import MAX_SEQ_LEN\n"
            f"{body}\n"
            'print("val_bpb: 1.0")\n'
            'print("num_steps: 10")\n'
            'print("peak_vram_mb: 100")\n'
        )
        assert _is_valid_full_python_file(code) is True

    def test_rejects_diff_like_snippet(self):
        code = "-DEPTH = 8\n+DEPTH = 6\n"
        assert _is_valid_full_python_file(code) is False

    def test_rejects_invalid_python(self):
        assert _is_valid_full_python_file("def x(:\n    pass\n") is False

    def test_rejects_partial_file_without_required_anchors(self):
        code = "import torch.nn as nn\n\nclass GPT(nn.Module):\n    pass\n"
        assert _is_valid_full_python_file(code) is False

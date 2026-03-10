"""Tests for experiment loop behavior and metadata extraction."""

from types import SimpleNamespace

import pytest

from spore.loop import ExperimentLoop, _extract_metadata


@pytest.mark.asyncio
async def test_apply_frontier_code_waits_for_delayed_peer_discovery(monkeypatch):
    applied: list[str] = []
    loop = ExperimentLoop.__new__(ExperimentLoop)
    best = SimpleNamespace(id="abc12345" * 8, code_cid="codecid", val_bpb=1.1)
    loop.node = SimpleNamespace(
        graph=SimpleNamespace(best=lambda: best),
        store=SimpleNamespace(get=lambda cid: None),
        gossip=SimpleNamespace(peers={"bootstrap:7470": object()}),
        fetch_code=None,
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

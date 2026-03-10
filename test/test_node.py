"""Tests for node bookkeeping around publish/sync."""

from __future__ import annotations

import hashlib
from test.conftest import make_record

import pytest

from spore.node import NodeConfig, SporeNode


@pytest.mark.asyncio
async def test_publish_experiment_records_reputation(tmp_path, keypair):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    record = make_record(keypair, description="local publish")

    await node.publish_experiment(record, code="print('hello')")

    stats = node.reputation.get_stats(node.node_id)
    assert stats["experiments_published"] == 1

    await node.stop()


def test_remote_experiment_records_publish_without_storing_fake_code(tmp_path, keypair):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    record = make_record(
        keypair,
        description="remote publish",
        diff="--- train.py\n+++ train.py\n@@\n-print('old')\n+print('new')\n",
    )

    node._on_remote_experiment(record)

    stats = node.reputation.get_stats(record.node_id)
    assert stats["experiments_published"] == 1
    assert node.store.get(record.code_cid) is None

    node.graph.close()
    node.reputation.close()


def test_remote_experiment_prefetches_artifact_from_source(
    tmp_path, keypair, monkeypatch
):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    record = make_record(keypair, description="remote publish")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        node.artifact,
        "prefetch",
        lambda owner, code_cid, preferred_peer=None: calls.append(
            (code_cid, preferred_peer or "")
        ),
    )

    node._on_remote_experiment(record, "peer:7470")

    assert calls == [(record.code_cid, "peer:7470")]
    node.graph.close()
    node.reputation.close()


@pytest.mark.asyncio
async def test_start_requests_pex_before_sync(tmp_path, monkeypatch):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    calls: list[tuple[str, str]] = []

    async def fake_start():
        return None

    async def fake_connect(host: str, port: int) -> bool:
        calls.append(("connect", f"{host}:{port}"))
        return True

    async def fake_request_pex(addr: str):
        calls.append(("pex", addr))

    async def fake_request_sync(addr: str, since_timestamp: int = 0):
        calls.append(("sync", addr))

    monkeypatch.setattr(node.gossip, "start", fake_start)
    monkeypatch.setattr(node.gossip, "connect_to_peer", fake_connect)
    monkeypatch.setattr(node.gossip, "request_pex", fake_request_pex)
    monkeypatch.setattr(node.gossip, "request_sync", fake_request_sync)

    await node.start()

    assert calls == [
        ("connect", "peer.sporemesh.com:7470"),
        ("pex", "peer.sporemesh.com:7470"),
        ("sync", "peer.sporemesh.com:7470"),
    ]

    node.graph.close()
    node.reputation.close()


@pytest.mark.asyncio
async def test_fetch_code_retries_newly_discovered_peers(tmp_path, monkeypatch):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    code_bytes = b"print('frontier')\n"
    code_cid = hashlib.sha256(code_bytes).hexdigest()
    node.gossip.peers["bootstrap:7470"] = (None, None)
    attempts: list[str] = []

    async def fake_request_code(addr: str, requested_cid: str, timeout: float = 30.0):
        assert requested_cid == code_cid
        attempts.append(addr)
        if addr == "bootstrap:7470":
            node.gossip.peers["source:7470"] = (None, None)
            return None
        if addr == "source:7470":
            return code_bytes
        return None

    monkeypatch.setattr(node.gossip, "request_code", fake_request_code)

    fetched = await node.fetch_code(code_cid)

    assert fetched == code_bytes
    assert attempts == ["bootstrap:7470", "source:7470"]
    assert node.store.get(code_cid) == code_bytes

    node.graph.close()
    node.reputation.close()

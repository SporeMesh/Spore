"""Tests for node bookkeeping around publish/sync."""

from __future__ import annotations

import asyncio
import hashlib
from test.conftest import make_record

import pytest

from spore.node import NodeConfig, SporeNode
from spore.wire import MessageType


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


def test_remote_parentless_experiment_creates_new_task_when_root_exists(
    tmp_path, keypair, second_keypair
):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    genesis = make_record(keypair, description="genesis")
    node._on_remote_experiment(genesis)
    competing_root = make_record(second_keypair, description="competing root")

    node._on_remote_experiment(competing_root)

    assert node.graph.count() == 2
    assert node.graph.get(genesis.id).task_id == genesis.id
    assert node.graph.get(competing_root.id).task_id == competing_root.id

    node.graph.close()
    node.profile.close()
    node.control.close()
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

    async def fake_request_control_sync(addr: str, since_timestamp: int = 0):
        calls.append(("control_sync", addr))

    monkeypatch.setattr(node.gossip, "start", fake_start)
    monkeypatch.setattr(node.gossip, "connect_to_peer", fake_connect)
    monkeypatch.setattr(node.gossip, "request_pex", fake_request_pex)
    monkeypatch.setattr(node.gossip, "request_sync", fake_request_sync)
    monkeypatch.setattr(node.gossip, "request_control_sync", fake_request_control_sync)

    await node.start()

    assert calls == [
        ("connect", "peer.sporemesh.com:7470"),
        ("pex", "peer.sporemesh.com:7470"),
        ("sync", "peer.sporemesh.com:7470"),
        ("control_sync", "peer.sporemesh.com:7470"),
    ]

    node.graph.close()
    node.control.close()
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
    node.control.close()
    node.reputation.close()


@pytest.mark.asyncio
async def test_publish_parentless_experiment_rejected_when_task_root_exists(
    tmp_path, keypair
):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    genesis = make_record(keypair, description="genesis")
    node._on_remote_experiment(genesis)
    node.active_task_id = genesis.id
    record = make_record(keypair, description="should fail")

    with pytest.raises(ValueError, match="task lineage rejected"):
        await node.publish_experiment(record, code="print('hello')\n")

    node.graph.close()
    node.profile.close()
    node.control.close()
    node.reputation.close()


def test_make_control_event_persists_signed_event(tmp_path):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))

    signed = node.make_control_event(
        MessageType.VERIFICATION,
        {
            "event_id": "verification:test",
            "experiment_id": "exp",
            "verified_node_id": "publisher",
            "verifier_id": node.node_id,
            "is_frontier": False,
        },
    )

    stored = node.control.list_since(0)
    assert signed["id"] == stored[0].id
    assert signed["type"] == stored[0].type

    node.graph.close()
    node.profile.close()
    node.control.close()
    node.reputation.close()


@pytest.mark.asyncio
async def test_control_sync_replays_verified_state(tmp_path, keypair):
    node_a = SporeNode(NodeConfig(port=18490, data_dir=str(tmp_path / "a")))
    node_b = SporeNode(
        NodeConfig(
            port=18491,
            peer=["127.0.0.1:18490"],
            data_dir=str(tmp_path / "b"),
        )
    )
    record = make_record(keypair, val_bpb=0.95, description="sync me")
    record.peak_vram_mb = float(record.peak_vram_mb)
    record.sign(keypair[0])

    await node_a.publish_experiment(record, code="print('hello')\n")
    verification = {
        "event_id": f"verification:{record.id}:{node_a.node_id}",
        "experiment_id": record.id,
        "verified_node_id": node_a.node_id,
        "verifier_id": node_a.node_id,
        "is_frontier": True,
    }
    node_a.challenger.on_verification(verification)
    node_a.make_control_event(MessageType.VERIFICATION, verification)

    await node_a.start(skip_peer=True)
    await node_b.start()
    await asyncio.sleep(0.3)

    synced = node_b.graph.get(record.id)
    assert synced is not None
    assert node_b.graph.is_verified(record.id)
    assert node_b.reputation.get_stats(node_a.node_id)["experiments_verified"] == 1

    await node_b.stop()
    await node_a.stop()

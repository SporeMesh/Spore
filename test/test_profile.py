"""Tests for signed node profiles."""

from __future__ import annotations

from spore.node import NodeConfig, SporeNode
from spore.profile import NodeProfile, NodeProfileStore


def test_node_profile_sign_and_verify(keypair):
    sk, node_id = keypair
    profile = NodeProfile(node_id=node_id, display_name="spore-node")
    profile.sign(sk)

    assert profile.verify_id()
    assert profile.verify_signature()


def test_profile_store_upsert_latest(tmp_path, keypair):
    sk, node_id = keypair
    store = NodeProfileStore(tmp_path / "profile.sqlite")

    older = NodeProfile(node_id=node_id, display_name="old", timestamp=10)
    older.sign(sk)
    newer = NodeProfile(node_id=node_id, display_name="new", timestamp=20)
    newer.sign(sk)

    assert store.upsert(older) is True
    assert store.upsert(newer) is True
    assert store.get(node_id).display_name == "new"
    store.close()


def test_remote_profile_is_persisted(tmp_path, keypair):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    sk, node_id = keypair
    profile = NodeProfile(node_id=node_id, display_name="remote-node")
    profile.sign(sk)

    node._on_remote_profile(profile)

    assert node.get_profile(node_id).display_name == "remote-node"
    node.graph.close()
    node.profile.close()
    node.reputation.close()


def test_local_profile_broadcasts_on_start(tmp_path, monkeypatch):
    node = SporeNode(NodeConfig(port=0, data_dir=str(tmp_path)))
    node.update_local_profile(display_name="local-node")
    published: list[str] = []

    async def fake_start():
        return None

    async def fake_connect(host: str, port: int) -> bool:
        return False

    async def fake_broadcast_profile(profile: NodeProfile):
        published.append(profile.display_name)

    monkeypatch.setattr(node.gossip, "start", fake_start)
    monkeypatch.setattr(node.gossip, "connect_to_peer", fake_connect)
    monkeypatch.setattr(node.gossip, "broadcast_profile", fake_broadcast_profile)

    import spore.node as node_module

    monkeypatch.setattr(node_module, "BOOTSTRAP_PEER", [])

    import asyncio

    asyncio.run(node.start())

    assert published == ["local-node"]
    node.graph.close()
    node.profile.close()
    node.reputation.close()

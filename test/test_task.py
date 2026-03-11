"""Tests for task manifests and task sync."""

from __future__ import annotations

import asyncio

import pytest

from spore.gossip import GossipServer
from spore.record import generate_keypair
from spore.task import TaskManifest


def test_task_manifest_sign_and_verify():
    signing_key, node_id = generate_keypair()
    manifest = TaskManifest(
        name="nanogpt-train",
        description="Optimize train.py",
        task_type="ml_train",
        artifact_type="python_train_script",
        metric="val_bpb",
        goal="minimize",
        base_code_cid="a" * 64,
        prepare_cid="b" * 64,
        dataset_cid="c" * 64,
        time_budget=300,
        created_by=node_id,
    )
    manifest.sign(signing_key)
    assert manifest.verify_id()
    assert manifest.verify_signature()


@pytest.mark.asyncio
async def test_task_sync_replays_task_manifests():
    signing_key, node_id = generate_keypair()
    manifest = TaskManifest(
        name="nanogpt-train",
        description="Optimize train.py",
        task_type="ml_train",
        artifact_type="python_train_script",
        metric="val_bpb",
        goal="minimize",
        base_code_cid="a" * 64,
        prepare_cid="b" * 64,
        dataset_cid="c" * 64,
        time_budget=300,
        created_by=node_id,
    )
    manifest.sign(signing_key)

    seen: list[str] = []
    server_a = GossipServer(
        host="127.0.0.1",
        port=19470,
        on_task_sync_request=lambda since: [manifest],
    )
    server_b = GossipServer(
        host="127.0.0.1",
        port=19471,
        on_task=lambda item: seen.append(item.task_id),
    )

    await server_a.start()
    await server_b.start()
    try:
        await server_b.connect_to_peer("127.0.0.1", 19470)
        await asyncio.sleep(0.05)
        response = await server_b.request_task_sync("127.0.0.1:19470")
        await asyncio.sleep(0.05)
        assert response == {"since": 0, "count": 1}
        assert seen == [manifest.task_id]
    finally:
        await server_a.stop()
        await server_b.stop()

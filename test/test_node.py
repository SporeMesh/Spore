"""Tests for node bookkeeping around publish/sync."""

from __future__ import annotations

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

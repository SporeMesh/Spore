"""Tests for migration and backfill on older local data."""

from __future__ import annotations

import sqlite3

from spore.node import NodeConfig, SporeNode
from spore.record import ExperimentRecord, Status, generate_keypair


def _make_legacy_record(
    keypair: tuple,
    *,
    parent: str | None = None,
    depth: int = 0,
    val_bpb: float = 1.0,
    description: str = "legacy",
) -> ExperimentRecord:
    signing_key, node_id = keypair
    record = ExperimentRecord(
        parent=parent,
        depth=depth,
        code_cid="a" * 64,
        diff="",
        dataset_cid="dataset_v1",
        prepare_cid="prepare_v1",
        time_budget=300,
        val_bpb=val_bpb,
        peak_vram_mb=1024,
        num_steps=10,
        num_params=1000,
        status=Status.KEEP,
        description=description,
        hypothesis="legacy",
        agent_model="legacy-agent",
        gpu_model="CPU",
        cuda_version="",
        torch_version="",
        node_id=node_id,
        version=1,
    )
    record.sign(signing_key)
    return record


def test_graph_migrates_old_schema_and_backfills_task_ids(tmp_path):
    data_dir = tmp_path / "node"
    db_dir = data_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "graph.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE experiment (
            id TEXT PRIMARY KEY,
            parent TEXT,
            depth INTEGER NOT NULL,
            code_cid TEXT NOT NULL,
            diff TEXT NOT NULL,
            dataset_cid TEXT NOT NULL,
            prepare_cid TEXT NOT NULL,
            time_budget INTEGER NOT NULL,
            val_bpb REAL NOT NULL,
            peak_vram_mb REAL NOT NULL,
            num_steps INTEGER NOT NULL,
            num_params INTEGER NOT NULL,
            status TEXT NOT NULL,
            description TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            agent_model TEXT NOT NULL,
            gpu_model TEXT NOT NULL,
            cuda_version TEXT NOT NULL,
            torch_version TEXT NOT NULL,
            node_id TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            signature TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            verified INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    keypair = generate_keypair()
    root = _make_legacy_record(keypair, description="root")
    child = _make_legacy_record(
        keypair,
        parent=root.id,
        depth=1,
        val_bpb=0.9,
        description="child",
    )
    conn.execute(
        """
        INSERT INTO experiment (
            id, parent, depth, code_cid, diff, dataset_cid, prepare_cid,
            time_budget, val_bpb, peak_vram_mb, num_steps, num_params, status,
            description, hypothesis, agent_model, gpu_model, cuda_version,
            torch_version, node_id, timestamp, signature, version, verified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            root.id,
            root.parent,
            root.depth,
            root.code_cid,
            root.diff,
            root.dataset_cid,
            root.prepare_cid,
            root.time_budget,
            root.val_bpb,
            root.peak_vram_mb,
            root.num_steps,
            root.num_params,
            root.status.value,
            root.description,
            root.hypothesis,
            root.agent_model,
            root.gpu_model,
            root.cuda_version,
            root.torch_version,
            root.node_id,
            root.timestamp,
            root.signature,
            root.version,
            0,
        ),
    )
    conn.execute(
        """
        INSERT INTO experiment (
            id, parent, depth, code_cid, diff, dataset_cid, prepare_cid,
            time_budget, val_bpb, peak_vram_mb, num_steps, num_params, status,
            description, hypothesis, agent_model, gpu_model, cuda_version,
            torch_version, node_id, timestamp, signature, version, verified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            child.id,
            child.parent,
            child.depth,
            child.code_cid,
            child.diff,
            child.dataset_cid,
            child.prepare_cid,
            child.time_budget,
            child.val_bpb,
            child.peak_vram_mb,
            child.num_steps,
            child.num_params,
            child.status.value,
            child.description,
            child.hypothesis,
            child.agent_model,
            child.gpu_model,
            child.cuda_version,
            child.torch_version,
            child.node_id,
            child.timestamp,
            child.signature,
            child.version,
            0,
        ),
    )
    conn.commit()
    conn.close()

    migrated = SporeNode(NodeConfig(port=0, data_dir=str(data_dir)))
    try:
        root_row = migrated.graph.get(root.id)
        child_row = migrated.graph.get(child.id)
        assert root_row is not None
        assert child_row is not None
        assert root_row.task_id == root.id
        assert child_row.task_id == root.id
        task = migrated.get_task(root.id)
        assert task is not None
        assert task["source"] == "legacy"
    finally:
        migrated.graph.close()
        migrated.profile.close()
        migrated.control.close()
        migrated.task.close()
        migrated.reputation.close()


def test_node_config_loads_old_config_with_new_defaults(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'host = "0.0.0.0"',
                "port = 7470",
                'peer = ["peer.sporemesh.com:7470"]',
                f'data_dir = "{tmp_path}"',
            ]
        )
    )
    config = NodeConfig.load(config_path)
    assert config.task_id == ""
    assert config.auto_update is True
    assert config.update_interval_sec == 21600
    assert "release-manifest.json" in config.update_manifest_url

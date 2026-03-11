"""Persistent task manifests and legacy task metadata."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .record import ExperimentRecord
from .task import TaskManifest, legacy_task_name

TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS task (
    task_id           TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    task_type         TEXT NOT NULL DEFAULT '',
    artifact_type     TEXT NOT NULL DEFAULT '',
    metric            TEXT NOT NULL DEFAULT '',
    goal              TEXT NOT NULL DEFAULT '',
    root_experiment_id TEXT NOT NULL DEFAULT '',
    created_by        TEXT NOT NULL DEFAULT '',
    timestamp         INTEGER NOT NULL DEFAULT 0,
    source            TEXT NOT NULL DEFAULT 'legacy',
    manifest_json     TEXT NOT NULL DEFAULT ''
);
"""


class TaskStore:
    """SQLite-backed task metadata store."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(TASK_SCHEMA)

    def close(self):
        self.conn.close()

    def upsert_manifest(self, manifest: TaskManifest) -> None:
        self.conn.execute(
            """
            INSERT INTO task (
                task_id, name, description, task_type, artifact_type, metric,
                goal, root_experiment_id, created_by, timestamp, source, manifest_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manifest', ?)
            ON CONFLICT(task_id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                task_type=excluded.task_type,
                artifact_type=excluded.artifact_type,
                metric=excluded.metric,
                goal=excluded.goal,
                created_by=excluded.created_by,
                timestamp=excluded.timestamp,
                source='manifest',
                manifest_json=excluded.manifest_json
            """,
            (
                manifest.task_id,
                manifest.name,
                manifest.description,
                manifest.task_type,
                manifest.artifact_type,
                manifest.metric,
                manifest.goal,
                "",
                manifest.created_by,
                manifest.timestamp,
                json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":")),
            ),
        )
        self.conn.commit()

    def ensure_legacy_task(self, root_id: str, record: ExperimentRecord) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO task (
                task_id, name, description, task_type, artifact_type, metric, goal,
                root_experiment_id, created_by, timestamp, source, manifest_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'legacy', '')
            """,
            (
                root_id,
                legacy_task_name(root_id),
                record.description or "Legacy backfilled task",
                "legacy",
                "python_train_script",
                "val_bpb",
                "minimize",
                root_id,
                record.node_id,
                record.timestamp,
            ),
        )
        self.conn.commit()

    def get(self, task_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM task WHERE task_id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM task ORDER BY timestamp DESC, task_id ASC"
        ).fetchall()
        return [dict(row) for row in rows]

    def manifests(self) -> list[TaskManifest]:
        rows = self.conn.execute(
            "SELECT manifest_json FROM task WHERE source = 'manifest' ORDER BY timestamp DESC, task_id ASC"
        ).fetchall()
        return [
            TaskManifest.from_json(row["manifest_json"])
            for row in rows
            if row["manifest_json"]
        ]

    def list_since(self, since_timestamp: int = 0) -> list[TaskManifest]:
        rows = self.conn.execute(
            """
            SELECT manifest_json
            FROM task
            WHERE source = 'manifest' AND timestamp > ?
            ORDER BY timestamp ASC, task_id ASC
            """,
            (since_timestamp,),
        ).fetchall()
        return [
            TaskManifest.from_json(row["manifest_json"])
            for row in rows
            if row["manifest_json"]
        ]

    def latest_timestamp(self) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(timestamp), 0) AS ts FROM task WHERE source = 'manifest'"
        ).fetchone()
        return int(row["ts"]) if row else 0

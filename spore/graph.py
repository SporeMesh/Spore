"""Research graph and task-aware experiment queries."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .record import ExperimentRecord, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment (
    id           TEXT PRIMARY KEY,
    parent       TEXT,
    depth        INTEGER NOT NULL,
    task_id      TEXT NOT NULL DEFAULT '',
    code_cid     TEXT NOT NULL,
    diff         TEXT NOT NULL,
    dataset_cid  TEXT NOT NULL,
    prepare_cid  TEXT NOT NULL,
    time_budget  INTEGER NOT NULL,
    val_bpb      REAL NOT NULL,
    peak_vram_mb REAL NOT NULL,
    num_steps    INTEGER NOT NULL,
    num_params   INTEGER NOT NULL,
    status       TEXT NOT NULL,
    description  TEXT NOT NULL,
    hypothesis   TEXT NOT NULL,
    agent_model  TEXT NOT NULL,
    gpu_model    TEXT NOT NULL,
    cuda_version TEXT NOT NULL,
    torch_version TEXT NOT NULL,
    node_id      TEXT NOT NULL,
    timestamp    INTEGER NOT NULL,
    signature    TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    verified     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (parent) REFERENCES experiment(id)
);
"""

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_parent ON experiment(parent);
CREATE INDEX IF NOT EXISTS idx_task_id ON experiment(task_id);
CREATE INDEX IF NOT EXISTS idx_status ON experiment(status);
CREATE INDEX IF NOT EXISTS idx_val_bpb ON experiment(val_bpb);
CREATE INDEX IF NOT EXISTS idx_gpu_model ON experiment(gpu_model);
CREATE INDEX IF NOT EXISTS idx_node_id ON experiment(node_id);
CREATE INDEX IF NOT EXISTS idx_timestamp ON experiment(timestamp);
"""


class ResearchGraph:
    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate_schema()
        self.conn.executescript(INDEX_SCHEMA)

    def close(self):
        self.conn.close()

    def insert(self, record: ExperimentRecord) -> bool:
        if not record.id:
            raise ValueError("Record has no CID — call record.sign() first")
        if not record.verify_cid():
            raise ValueError(f"CID mismatch for record {record.id}")
        try:
            self.conn.execute(
                """INSERT INTO experiment (
                    id, parent, depth, task_id, code_cid, diff, dataset_cid,
                    prepare_cid, time_budget, val_bpb, peak_vram_mb, num_steps,
                    num_params, status, description, hypothesis, agent_model,
                    gpu_model, cuda_version, torch_version, node_id, timestamp,
                    signature, version
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )""",
                (
                    record.id,
                    record.parent,
                    record.depth,
                    record.task_id,
                    record.code_cid,
                    record.diff,
                    record.dataset_cid,
                    record.prepare_cid,
                    record.time_budget,
                    record.val_bpb,
                    record.peak_vram_mb,
                    record.num_steps,
                    record.num_params,
                    record.status.value
                    if isinstance(record.status, Status)
                    else record.status,
                    record.description,
                    record.hypothesis,
                    record.agent_model,
                    record.gpu_model,
                    record.cuda_version,
                    record.torch_version,
                    record.node_id,
                    record.timestamp,
                    record.signature,
                    record.version,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get(self, cid: str) -> ExperimentRecord | None:
        row = self.conn.execute(
            "SELECT * FROM experiment WHERE id = ?", (cid,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def children(self, cid: str) -> list[ExperimentRecord]:
        rows = self.conn.execute(
            "SELECT * FROM experiment WHERE parent = ? ORDER BY timestamp",
            (cid,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def ancestors(self, cid: str) -> list[ExperimentRecord]:
        chain: list[ExperimentRecord] = []
        current = cid
        while current:
            record = self.get(current)
            if not record:
                break
            chain.append(record)
            current = record.parent
        return chain

    def frontier(self, gpu_class: str | None = None) -> list[ExperimentRecord]:
        return self._frontier_query(task_id=None, gpu_class=gpu_class)

    def frontier_by_task(
        self, task_id: str, gpu_class: str | None = None
    ) -> list[ExperimentRecord]:
        return self._frontier_query(task_id=task_id, gpu_class=gpu_class)

    def best(self, gpu_class: str | None = None) -> ExperimentRecord | None:
        frontier = self.frontier(gpu_class=gpu_class)
        return frontier[0] if frontier else None

    def best_by_task(
        self, task_id: str, gpu_class: str | None = None
    ) -> ExperimentRecord | None:
        frontier = self.frontier_by_task(task_id, gpu_class=gpu_class)
        return frontier[0] if frontier else None

    def recent(self, limit: int = 20) -> list[ExperimentRecord]:
        rows = self.conn.execute(
            "SELECT * FROM experiment ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def recent_by_task(self, task_id: str, limit: int = 20) -> list[ExperimentRecord]:
        rows = self.conn.execute(
            "SELECT * FROM experiment WHERE task_id = ? ORDER BY timestamp DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM experiment").fetchone()
        return int(row["n"]) if row else 0

    def all_records(self) -> list[ExperimentRecord]:
        rows = self.conn.execute(
            "SELECT * FROM experiment ORDER BY depth ASC, timestamp ASC"
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def by_node(self, node_id: str) -> list[ExperimentRecord]:
        rows = self.conn.execute(
            "SELECT * FROM experiment WHERE node_id = ? ORDER BY timestamp",
            (node_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def by_task(self, task_id: str) -> list[ExperimentRecord]:
        rows = self.conn.execute(
            "SELECT * FROM experiment WHERE task_id = ? ORDER BY depth ASC, timestamp ASC",
            (task_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def all_task_ids(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT task_id FROM experiment WHERE task_id != '' ORDER BY task_id"
        ).fetchall()
        return [row["task_id"] for row in rows]

    def root_ids(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT id FROM experiment WHERE parent IS NULL"
        ).fetchall()
        return {row["id"] for row in rows}

    def root_ids_by_task(self, task_id: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT id FROM experiment WHERE task_id = ? AND parent IS NULL",
            (task_id,),
        ).fetchall()
        return {row["id"] for row in rows}

    def verified_ids(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT id FROM experiment WHERE verified = 1"
        ).fetchall()
        return {row["id"] for row in rows}

    def mark_verified(self, cid: str, verified: bool = True):
        self.conn.execute(
            "UPDATE experiment SET verified = ? WHERE id = ?",
            (1 if verified else 0, cid),
        )
        self.conn.commit()

    def is_verified(self, cid: str) -> bool:
        row = self.conn.execute(
            "SELECT verified FROM experiment WHERE id = ?",
            (cid,),
        ).fetchone()
        return bool(row and row["verified"])

    def backfill_task_ids(self) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT id, parent, task_id FROM experiment ORDER BY depth ASC, timestamp ASC"
        ).fetchall()
        parent_by_id = {row["id"]: row["parent"] for row in rows}
        assigned: dict[str, str] = {}

        def root_for(record_id: str) -> str:
            root_id = assigned.get(record_id)
            if root_id:
                return root_id
            parent = parent_by_id.get(record_id)
            if not parent:
                assigned[record_id] = record_id
                return record_id
            root_id = root_for(parent)
            assigned[record_id] = root_id
            return root_id

        updates: list[tuple[str, str]] = []
        for row in rows:
            task_id = row["task_id"] or root_for(row["id"])
            assigned[row["id"]] = task_id
            if row["task_id"] != task_id:
                updates.append((task_id, row["id"]))
        if updates:
            self.conn.executemany(
                "UPDATE experiment SET task_id = ? WHERE id = ?",
                updates,
            )
            self.conn.commit()
        return assigned

    def ascii_tree(self, max_depth: int = 50, task_id: str | None = None) -> str:
        if task_id:
            roots = self.conn.execute(
                """
                SELECT * FROM experiment
                WHERE parent IS NULL AND task_id = ?
                ORDER BY timestamp
                """,
                (task_id,),
            ).fetchall()
        else:
            roots = self.conn.execute(
                "SELECT * FROM experiment WHERE parent IS NULL ORDER BY timestamp"
            ).fetchall()
        if not roots:
            return "(empty graph)"
        lines: list[str] = []
        for root in roots:
            self._render_node(
                self._row_to_record(root),
                "",
                True,
                lines,
                max_depth,
                0,
                task_id,
            )
        return "\n".join(lines)

    def _frontier_query(
        self, *, task_id: str | None, gpu_class: str | None
    ) -> list[ExperimentRecord]:
        query = """
            SELECT e.* FROM experiment e
            WHERE e.status = 'keep'
        """
        params: list[object] = []
        if task_id is not None:
            query += " AND e.task_id = ?"
            params.append(task_id)
        query += """
            AND NOT EXISTS (
                SELECT 1 FROM experiment c
                WHERE c.parent = e.id
        """
        if task_id is not None:
            query += " AND c.task_id = e.task_id"
        query += """
                AND c.status = 'keep'
                AND c.val_bpb < e.val_bpb
            )
        """
        if gpu_class:
            query += " AND e.gpu_model = ?"
            params.append(gpu_class)
        query += " ORDER BY e.val_bpb ASC"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _render_node(
        self,
        record: ExperimentRecord,
        prefix: str,
        is_last: bool,
        lines: list[str],
        max_depth: int,
        current_depth: int,
        task_id: str | None,
    ):
        if current_depth > max_depth:
            return
        connector = "\u2514\u2500 " if is_last else "\u251c\u2500 "
        status_icon = {"keep": "+", "discard": "x", "crash": "!"}
        status = (
            record.status.value if isinstance(record.status, Status) else record.status
        )
        icon = status_icon.get(status, "?")
        lines.append(
            f"{prefix}{connector}[{icon}] {record.id[:8]} task={record.task_id[:8]} val_bpb={record.val_bpb:.6f} | {record.description[:40]}"
        )
        child_prefix = prefix + ("   " if is_last else "\u2502  ")
        children = [
            child
            for child in self.children(record.id)
            if task_id is None or child.task_id == task_id
        ]
        for index, child in enumerate(children):
            self._render_node(
                child,
                child_prefix,
                index == len(children) - 1,
                lines,
                max_depth,
                current_depth + 1,
                task_id,
            )

    def _row_to_record(self, row: sqlite3.Row) -> ExperimentRecord:
        return ExperimentRecord(
            parent=row["parent"],
            depth=row["depth"],
            code_cid=row["code_cid"],
            diff=row["diff"],
            dataset_cid=row["dataset_cid"],
            prepare_cid=row["prepare_cid"],
            time_budget=row["time_budget"],
            val_bpb=row["val_bpb"],
            peak_vram_mb=row["peak_vram_mb"],
            num_steps=row["num_steps"],
            num_params=row["num_params"],
            status=Status(row["status"]),
            description=row["description"],
            hypothesis=row["hypothesis"],
            agent_model=row["agent_model"],
            gpu_model=row["gpu_model"],
            cuda_version=row["cuda_version"],
            torch_version=row["torch_version"],
            node_id=row["node_id"],
            task_id=row["task_id"],
            timestamp=row["timestamp"],
            signature=row["signature"],
            id=row["id"],
            version=row["version"],
        )

    def _migrate_schema(self):
        cols = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(experiment)").fetchall()
        }
        if "task_id" not in cols:
            self.conn.execute(
                "ALTER TABLE experiment ADD COLUMN task_id TEXT NOT NULL DEFAULT ''"
            )
            self.conn.commit()

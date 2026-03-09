"""Research Graph — a SQLite-backed Merkle-DAG of experiments.

The graph is append-only: experiments are inserted but never deleted.
The frontier (best unbeaten experiments) is computed locally from the graph.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .record import ExperimentRecord, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment (
    id          TEXT PRIMARY KEY,
    parent      TEXT,
    depth       INTEGER NOT NULL,
    code_cid    TEXT NOT NULL,
    diff        TEXT NOT NULL,
    dataset_cid TEXT NOT NULL,
    prepare_cid TEXT NOT NULL,
    time_budget INTEGER NOT NULL,
    val_bpb     REAL NOT NULL,
    peak_vram_mb REAL NOT NULL,
    num_steps   INTEGER NOT NULL,
    num_params  INTEGER NOT NULL,
    status      TEXT NOT NULL,
    description TEXT NOT NULL,
    hypothesis  TEXT NOT NULL,
    agent_model TEXT NOT NULL,
    gpu_model   TEXT NOT NULL,
    cuda_version TEXT NOT NULL,
    torch_version TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    signature   TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    verified    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (parent) REFERENCES experiment(id)
);

CREATE INDEX IF NOT EXISTS idx_parent ON experiment(parent);
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

    def close(self):
        self.conn.close()

    def insert(self, record: ExperimentRecord) -> bool:
        """Insert an experiment record. Returns False if CID already exists."""
        if not record.id:
            raise ValueError("Record has no CID — call record.sign() first")

        if not record.verify_cid():
            raise ValueError(f"CID mismatch for record {record.id}")

        try:
            self.conn.execute(
                """INSERT INTO experiment (
                    id, parent, depth, code_cid, diff, dataset_cid, prepare_cid,
                    time_budget, val_bpb, peak_vram_mb, num_steps, num_params,
                    status, description, hypothesis, agent_model, gpu_model,
                    cuda_version, torch_version, node_id, timestamp, signature,
                    version
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?
                )""",
                (
                    record.id,
                    record.parent,
                    record.depth,
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
            return False  # CID already exists (dedup)

    def get(self, cid: str) -> ExperimentRecord | None:
        """Get an experiment by CID."""
        row = self.conn.execute(
            "SELECT * FROM experiment WHERE id = ?", (cid,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def children(self, cid: str) -> list[ExperimentRecord]:
        """Get all experiments whose parent is this CID."""
        rows = self.conn.execute(
            "SELECT * FROM experiment WHERE parent = ? ORDER BY timestamp",
            (cid,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def ancestors(self, cid: str) -> list[ExperimentRecord]:
        """Walk the parent chain from CID to genesis."""
        chain = []
        current = cid
        while current:
            record = self.get(current)
            if not record:
                break
            chain.append(record)
            current = record.parent
        return chain

    def frontier(self, gpu_class: str | None = None) -> list[ExperimentRecord]:
        """Compute the frontier — best unbeaten experiments.

        An experiment is on the frontier if:
        1. Its status is 'keep'
        2. No child has a lower val_bpb

        Optionally filtered by GPU class.
        """
        query = """
            SELECT e.* FROM experiment e
            WHERE e.status = 'keep'
            AND NOT EXISTS (
                SELECT 1 FROM experiment c
                WHERE c.parent = e.id
                AND c.status = 'keep'
                AND c.val_bpb < e.val_bpb
            )
        """
        params: list = []
        if gpu_class:
            query += " AND e.gpu_model = ?"
            params.append(gpu_class)

        query += " ORDER BY e.val_bpb ASC"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def best(self, gpu_class: str | None = None) -> ExperimentRecord | None:
        """Get the single best experiment (lowest val_bpb)."""
        f = self.frontier(gpu_class)
        return f[0] if f else None

    def recent(self, limit: int = 20) -> list[ExperimentRecord]:
        """Get the most recent experiments."""
        rows = self.conn.execute(
            "SELECT * FROM experiment ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM experiment").fetchone()
        return row[0]

    def all_records(self) -> list[ExperimentRecord]:
        """Get all experiments ordered by depth then timestamp."""
        rows = self.conn.execute(
            "SELECT * FROM experiment ORDER BY depth ASC, timestamp ASC"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def by_node(self, node_id: str) -> list[ExperimentRecord]:
        """Get all experiments from a specific node."""
        rows = self.conn.execute(
            "SELECT * FROM experiment WHERE node_id = ? ORDER BY timestamp",
            (node_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def mark_verified(self, cid: str, verified: bool = True):
        """Mark an experiment as verified (or not)."""
        self.conn.execute(
            "UPDATE experiment SET verified = ? WHERE id = ?",
            (1 if verified else 0, cid),
        )
        self.conn.commit()

    def ascii_tree(self, max_depth: int = 50) -> str:
        """Render the graph as an ASCII tree."""
        roots = self.conn.execute(
            "SELECT * FROM experiment WHERE parent IS NULL ORDER BY timestamp"
        ).fetchall()
        if not roots:
            return "(empty graph)"

        lines: list[str] = []
        for root in roots:
            self._render_node(self._row_to_record(root), "", True, lines, max_depth, 0)
        return "\n".join(lines)

    def _render_node(
        self,
        record: ExperimentRecord,
        prefix: str,
        is_last: bool,
        lines: list[str],
        max_depth: int,
        current_depth: int,
    ):
        if current_depth > max_depth:
            return

        connector = "\u2514\u2500 " if is_last else "\u251c\u2500 "
        status_icon = {"keep": "+", "discard": "x", "crash": "!"}
        icon = status_icon.get(
            record.status.value if isinstance(record.status, Status) else record.status,
            "?",
        )
        cid_short = record.id[:8] if record.id else "????????"
        line = f"{prefix}{connector}[{icon}] {cid_short} val_bpb={record.val_bpb:.6f} | {record.description[:40]}"
        lines.append(line)

        kids = self.children(record.id)
        child_prefix = prefix + ("   " if is_last else "\u2502  ")
        for i, child in enumerate(kids):
            self._render_node(
                child,
                child_prefix,
                i == len(kids) - 1,
                lines,
                max_depth,
                current_depth + 1,
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
            timestamp=row["timestamp"],
            signature=row["signature"],
            id=row["id"],
            version=row["version"],
        )

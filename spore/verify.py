"""Verification — spot-checking, tolerance bands, reputation scoring.

Handles probabilistic verification of experiment results and maintains
a reputation system for nodes in the network.
"""

from __future__ import annotations

import random
import sqlite3
import statistics
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .record import ExperimentRecord, Status

# Default tolerance bands (val_bpb difference)
# These should be calibrated empirically per GPU class
DEFAULT_TOLERANCE = 0.002
GPU_TOLERANCE: dict[str, float] = {
    "H100-SXM5-80GB": 0.0015,
    "A100-SXM4-80GB": 0.0015,
    "RTX_4090": 0.002,
    "RTX_3090": 0.003,
}


class DisputeOutcome(str, Enum):
    UPHELD = "upheld"  # Original claim was valid
    REJECTED = "rejected"  # Original claim was fabricated


@dataclass
class VerificationResult:
    experiment_id: str
    verifier_node_id: str
    verifier_val_bpb: float
    verifier_gpu: str
    within_tolerance: bool


@dataclass
class DisputeRecord:
    experiment_id: str
    challenger_id: str
    challenger_bpb: float
    challenger_gpu: str
    verifier_result: list[VerificationResult]
    outcome: DisputeOutcome
    ground_truth_bpb: float  # Median of all results


REPUTATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS reputation (
    node_id     TEXT PRIMARY KEY,
    score       REAL NOT NULL DEFAULT 0.0,
    experiments_published   INTEGER NOT NULL DEFAULT 0,
    experiments_verified    INTEGER NOT NULL DEFAULT 0,
    verifications_performed INTEGER NOT NULL DEFAULT 0,
    disputes_won            INTEGER NOT NULL DEFAULT 0,
    disputes_lost           INTEGER NOT NULL DEFAULT 0
);
"""


class ReputationStore:
    """SQLite-backed reputation tracking for network nodes."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(REPUTATION_SCHEMA)

    def close(self):
        self.conn.close()

    def get_score(self, node_id: str) -> float:
        row = self.conn.execute(
            "SELECT score FROM reputation WHERE node_id = ?", (node_id,)
        ).fetchone()
        return row["score"] if row else 0.0

    def get_stats(self, node_id: str) -> dict:
        row = self.conn.execute(
            "SELECT * FROM reputation WHERE node_id = ?", (node_id,)
        ).fetchone()
        if not row:
            return {
                "node_id": node_id,
                "score": 0.0,
                "experiments_published": 0,
                "experiments_verified": 0,
                "verifications_performed": 0,
                "disputes_won": 0,
                "disputes_lost": 0,
            }
        return dict(row)

    def update_score(self, node_id: str, delta: float, field: str | None = None):
        """Update a node's reputation score and optionally increment a counter."""
        self._ensure_node(node_id)
        new_score = max(-100.0, min(100.0, self.get_score(node_id) + delta))
        if field:
            self.conn.execute(
                f"UPDATE reputation SET score = ?, {field} = {field} + 1 WHERE node_id = ?",
                (new_score, node_id),
            )
        else:
            self.conn.execute(
                "UPDATE reputation SET score = ? WHERE node_id = ?",
                (new_score, node_id),
            )
        self.conn.commit()

    def record_published(self, node_id: str, record: ExperimentRecord):
        """Update reputation when a node publishes an experiment."""
        # No reputation change on publish — only on verification
        self._ensure_node(node_id)
        self.conn.execute(
            "UPDATE reputation SET experiments_published = experiments_published + 1 WHERE node_id = ?",
            (node_id,),
        )
        self.conn.commit()

    def record_verified(
        self, node_id: str, record: ExperimentRecord, is_frontier: bool = False
    ):
        """Update reputation when a node's experiment is verified."""
        status = (
            record.status
            if isinstance(record.status, Status)
            else Status(record.status)
        )
        if status == Status.KEEP:
            delta = 2.0 if is_frontier else 1.0
        elif status == Status.DISCARD:
            delta = 0.3
        else:
            delta = 0.1
        self.update_score(node_id, delta, "experiments_verified")

    def verification_performed(self, verifier_id: str):
        """Reward a node for performing a verification."""
        self.update_score(verifier_id, 0.5, "verifications_performed")

    def dispute_resolved(self, winner_id: str, loser_id: str):
        """Update reputation after a dispute is resolved."""
        self.update_score(winner_id, 1.0, "disputes_won")
        self.update_score(loser_id, -5.0, "disputes_lost")

    def leaderboard(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM reputation ORDER BY score DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def backfill_published(self, records: list[ExperimentRecord]):
        """Ensure publish counts exist for already-synced experiments."""
        counts = Counter(r.node_id for r in records if r.node_id)
        for node_id, published in counts.items():
            self._ensure_node(node_id)
            row = self.conn.execute(
                "SELECT experiments_published FROM reputation WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            current = row["experiments_published"] if row else 0
            if current < published:
                self.conn.execute(
                    "UPDATE reputation SET experiments_published = ? WHERE node_id = ?",
                    (published, node_id),
                )
        self.conn.commit()

    def _ensure_node(self, node_id: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO reputation (node_id, score) VALUES (?, 0.0)",
            (node_id,),
        )
        self.conn.commit()


class Verifier:
    """Handles experiment verification, challenges, and dispute resolution."""

    def __init__(
        self,
        reputation: ReputationStore,
        spot_check_rate: float = 0.05,
        tolerance: float = DEFAULT_TOLERANCE,
        gpu_tolerance: dict[str, float] | None = None,
    ):
        self.reputation = reputation
        self.spot_check_rate = spot_check_rate
        self.default_tolerance = tolerance
        self.gpu_tolerance = gpu_tolerance or GPU_TOLERANCE

    def get_tolerance(self, gpu_model: str) -> float:
        """Get the tolerance band for a specific GPU model."""
        return self.gpu_tolerance.get(gpu_model, self.default_tolerance)

    def should_verify(self, record: ExperimentRecord) -> bool:
        """Decide whether to spot-check this experiment.

        Higher probability for:
        - Low-reputation nodes
        - Frontier-advancing experiments
        - Statistically suspicious results
        """
        base_rate = self.spot_check_rate

        # Increase rate for low-reputation nodes
        node_score = self.reputation.get_score(record.node_id)
        if node_score < 0:
            base_rate = min(1.0, base_rate * 3)
        elif node_score < 5:
            base_rate = min(1.0, base_rate * 2)

        # Increase rate for very good results (potential fabrication)
        if record.val_bpb < 0.9:  # Suspiciously good
            base_rate = min(1.0, base_rate * 2)

        return random.random() < base_rate

    def verify_result(
        self,
        record: ExperimentRecord,
        actual_bpb: float,
        verifier_node_id: str,
        verifier_gpu: str,
    ) -> VerificationResult:
        """Verify an experiment result against an actual re-run.

        Only compares results from the same GPU class.
        """
        if verifier_gpu != record.gpu_model:
            # Cross-GPU verification not supported
            return VerificationResult(
                experiment_id=record.id,
                verifier_node_id=verifier_node_id,
                verifier_val_bpb=actual_bpb,
                verifier_gpu=verifier_gpu,
                within_tolerance=True,  # Can't compare across GPU classes
            )

        tolerance = self.get_tolerance(record.gpu_model)
        diff = abs(record.val_bpb - actual_bpb)
        within = diff <= tolerance

        # Update reputation
        self.reputation.verification_performed(verifier_node_id)

        return VerificationResult(
            experiment_id=record.id,
            verifier_node_id=verifier_node_id,
            verifier_val_bpb=actual_bpb,
            verifier_gpu=verifier_gpu,
            within_tolerance=within,
        )

    def challenge(
        self,
        record: ExperimentRecord,
        challenger_bpb: float,
        challenger_id: str,
        challenger_gpu: str,
    ) -> bool:
        """Initiate a challenge against an experiment result.

        Returns True if the challenge is valid (exceeds tolerance band).
        """
        if challenger_gpu != record.gpu_model:
            return False  # Can't challenge across GPU classes

        tolerance = self.get_tolerance(record.gpu_model)
        diff = abs(record.val_bpb - challenger_bpb)
        return diff > tolerance

    def resolve_dispute(
        self,
        record: ExperimentRecord,
        challenger_bpb: float,
        challenger_id: str,
        challenger_gpu: str,
        verifier_results: list[VerificationResult],
    ) -> DisputeRecord:
        """Resolve a dispute using median of all results.

        Expects 3 verifier results (+ original + challenger = 5 total).
        """
        all_bpb = [record.val_bpb, challenger_bpb] + [
            v.verifier_val_bpb for v in verifier_results
        ]
        ground_truth = statistics.median(all_bpb)
        tolerance = self.get_tolerance(record.gpu_model)

        original_diff = abs(record.val_bpb - ground_truth)
        challenger_diff = abs(challenger_bpb - ground_truth)

        if original_diff > tolerance:
            # Original was fabricated
            outcome = DisputeOutcome.REJECTED
            self.reputation.dispute_resolved(
                winner_id=challenger_id, loser_id=record.node_id
            )
        else:
            # Original was valid, challenger was wrong
            outcome = DisputeOutcome.UPHELD
            self.reputation.dispute_resolved(
                winner_id=record.node_id, loser_id=challenger_id
            )

        return DisputeRecord(
            experiment_id=record.id,
            challenger_id=challenger_id,
            challenger_bpb=challenger_bpb,
            challenger_gpu=challenger_gpu,
            verifier_result=verifier_results,
            outcome=outcome,
            ground_truth_bpb=ground_truth,
        )

    def check_suspicious(self, record: ExperimentRecord) -> list[str]:
        """Run heuristic checks for suspicious results. Returns list of flags."""
        flags = []

        # Check training time
        if record.time_budget > 0 and abs(record.time_budget - 300) > 60:
            flags.append(f"unusual_time_budget:{record.time_budget}s")

        # Check val_bpb = 0 for non-crash
        status = (
            record.status
            if isinstance(record.status, Status)
            else Status(record.status)
        )
        if record.val_bpb == 0 and status != Status.CRASH:
            flags.append("zero_bpb_non_crash")

        # Check suspiciously good results
        if record.val_bpb > 0 and record.val_bpb < 0.5:
            flags.append(f"suspiciously_low_bpb:{record.val_bpb}")

        # Check VRAM consistency with GPU
        known_vram: dict[str, float] = {
            "H100-SXM5-80GB": 81920,
            "A100-SXM4-80GB": 81920,
            "RTX_4090": 24576,
            "RTX_3090": 24576,
            "RTX_3060": 12288,
        }
        if record.gpu_model in known_vram:
            max_vram = known_vram[record.gpu_model]
            if record.peak_vram_mb > max_vram * 1.1:
                flags.append(
                    f"vram_exceeds_gpu_max:{record.peak_vram_mb:.0f}>{max_vram:.0f}"
                )

        return flags

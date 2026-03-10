"""Verification — spot-checking, tolerance bands, reputation scoring.

Handles probabilistic verification of experiment results and maintains
a reputation system for nodes in the network.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from enum import Enum

from .gpu import gpu_verification_class, normalize_gpu_model
from .record import ExperimentRecord, Status
from .reputation import ReputationStore

# Default tolerance bands (val_bpb difference)
# These should be calibrated empirically per GPU class
DEFAULT_TOLERANCE = 0.002
GPU_TOLERANCE: dict[str, float] = {
    "H100": 0.0015,
    "A100": 0.0015,
    "RTX_5090": 0.002,
    "RTX_4090": 0.002,
    "RTX_3090": 0.003,
    "RTX_3060": 0.003,
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
        return self.gpu_tolerance.get(
            gpu_verification_class(gpu_model), self.default_tolerance
        )

    def same_gpu_class(self, left_gpu: str, right_gpu: str) -> bool:
        """Return True if two GPU strings belong to the same verification class."""
        return gpu_verification_class(left_gpu) == gpu_verification_class(right_gpu)

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
        if not self.same_gpu_class(verifier_gpu, record.gpu_model):
            # Cross-GPU verification not supported
            return VerificationResult(
                experiment_id=record.id,
                verifier_node_id=verifier_node_id,
                verifier_val_bpb=actual_bpb,
                verifier_gpu=normalize_gpu_model(verifier_gpu),
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
            verifier_gpu=normalize_gpu_model(verifier_gpu),
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
        if not self.same_gpu_class(challenger_gpu, record.gpu_model):
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
        else:
            # Original was valid, challenger was wrong
            outcome = DisputeOutcome.UPHELD

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
            "H100": 81920,
            "A100": 81920,
            "RTX_5090": 32768,
            "RTX_4090": 24576,
            "RTX_3090": 24576,
            "RTX_3060": 12288,
        }
        normalized_gpu = gpu_verification_class(record.gpu_model)
        if normalized_gpu in known_vram:
            max_vram = known_vram[normalized_gpu]
            if record.peak_vram_mb > max_vram * 1.1:
                flags.append(
                    f"vram_exceeds_gpu_max:{record.peak_vram_mb:.0f}>{max_vram:.0f}"
                )

        return flags

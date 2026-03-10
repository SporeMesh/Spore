"""Challenge state helpers and event application."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .gpu import gpu_verification_class
from .record import ExperimentRecord
from .verify import DisputeOutcome, VerificationResult, Verifier


@dataclass
class PendingChallenge:
    experiment: ExperimentRecord
    challenger_id: str
    challenger_bpb: float
    challenger_gpu: str
    required_responses: int
    response: list[VerificationResult] = field(default_factory=list)
    responder_id: set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)


def apply_verification_event(node, verifier: Verifier, payload: dict):
    """Apply a successful spot-check network-wide."""
    experiment_id = payload.get("experiment_id", "")
    record = node.graph.get(experiment_id)
    if record is None:
        return

    event_id = payload.get(
        "event_id",
        f"verification:{experiment_id}:{payload.get('verifier_id', '')}",
    )
    if not verifier.reputation.record_event(event_id, "verification"):
        return

    verifier_id = payload.get("verifier_id", "")
    if verifier_id:
        verifier.reputation.verification_performed(verifier_id)

    if not node.graph.is_verified(experiment_id):
        verifier.reputation.record_verified(
            payload.get("verified_node_id", record.node_id),
            record,
            is_frontier=bool(payload.get("is_frontier")),
        )
        node.graph.mark_verified(experiment_id, True)


def apply_dispute_event(node, verifier: Verifier, payload: dict):
    """Apply the reputation and verification effects of a dispute."""
    experiment_id = payload.get("experiment_id", "")
    event_id = payload.get(
        "event_id",
        f"dispute:{experiment_id}:{payload.get('challenger_id', '')}",
    )
    if not verifier.reputation.record_event(event_id, "dispute"):
        return False

    outcome = payload.get("outcome", "")
    if outcome == DisputeOutcome.UPHELD.value:
        node.graph.mark_verified(experiment_id, True)
        verifier.reputation.dispute_resolved(
            winner_id=payload.get("original_node_id", ""),
            loser_id=payload.get("challenger_id", ""),
        )
    elif outcome == DisputeOutcome.REJECTED.value:
        verifier.reputation.dispute_resolved(
            winner_id=payload.get("challenger_id", ""),
            loser_id=payload.get("original_node_id", ""),
        )
    return True


def count_independent_verifiers(
    node, record: ExperimentRecord, challenger_id: str
) -> int:
    """Count distinct compatible nodes excluding challenger and publisher."""
    eligible: set[str] = set()
    target_class = gpu_verification_class(record.gpu_model)
    for candidate in node.graph.all_records():
        candidate_id = candidate.node_id
        if candidate_id in {challenger_id, record.node_id}:
            continue
        if gpu_verification_class(candidate.gpu_model) == target_class:
            eligible.add(candidate_id)
    return len(eligible)

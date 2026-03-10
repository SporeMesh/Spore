"""Challenge coordinator — drives the verification protocol over gossip.

Flow:
1. Node receives experiment → spot-check decision (probabilistic)
2. If spot-check: re-run experiment, compare val_bpb
3. If outside tolerance: broadcast CHALLENGE to network
4. 3 verifiers re-run and send CHALLENGE_RESPONSE
5. Challenger collects responses, resolves dispute, broadcasts DISPUTE
6. Reputation updated for winner/loser
"""

from __future__ import annotations

import asyncio
import logging
import time

from .challenge_state import (
    PendingChallenge,
    apply_dispute_event,
    apply_verification_event,
    count_independent_verifiers,
)
from .gpu import normalize_gpu_model
from .record import ExperimentRecord
from .verify import (
    DisputeOutcome,
    VerificationResult,
    Verifier,
)

log = logging.getLogger(__name__)

VERIFIER_COUNT = 3
CHALLENGE_TIMEOUT = 600  # 10 min to collect verifier responses


class ChallengeCoordinator:
    """Manages the challenge/dispute lifecycle over the gossip network."""

    def __init__(self, verifier: Verifier, node_id: str, gpu_model: str):
        self.verifier = verifier
        self.node_id = node_id
        self.gpu_model = normalize_gpu_model(gpu_model)
        self._pending: dict[str, PendingChallenge] = {}
        self._node = None  # Set by node after init

    def set_node(self, node):
        self._node = node

    def on_experiment_received(self, record: ExperimentRecord):
        """Called when a new experiment arrives. Decides whether to spot-check."""
        if not self.verifier.should_verify(record):
            return
        if not self.verifier.same_gpu_class(record.gpu_model, self.gpu_model):
            return  # Can only verify same GPU class
        log.info("Spot-checking experiment %s...", record.id[:8])
        asyncio.create_task(self._run_spot_check(record))

    async def _run_spot_check(self, record: ExperimentRecord):
        """Re-run an experiment and challenge if result differs."""
        if self._node is None or self._node.workspace is None:
            return

        # Re-run the experiment with the recorded code
        code_bytes = await self._get_code_bytes(record)
        if not code_bytes:
            log.warning("No code available for spot-check of %s", record.id[:8])
            return

        if self._node.training.busy():
            log.info(
                "Queueing spot-check for %s until local training slot is free",
                record.id[:8],
            )
        result = await self._node.training.run_isolated(
            self._node.workspace, code_bytes.decode("utf-8")
        )

        if not result.success:
            log.warning("Spot-check run failed for %s", record.id[:8])
            return

        # Check if result is within tolerance
        is_valid = self.verifier.challenge(
            record, result.val_bpb, self.node_id, self.gpu_model
        )
        if not is_valid:
            log.info(
                "Spot-check passed for %s (%.6f vs %.6f)",
                record.id[:8],
                record.val_bpb,
                result.val_bpb,
            )
            payload = {
                "event_id": f"verification:{record.id}:{self.node_id}",
                "experiment_id": record.id,
                "verified_node_id": record.node_id,
                "verifier_id": self.node_id,
                "verifier_gpu": self.gpu_model,
                "verifier_bpb": result.val_bpb,
                "is_frontier": record.id in {r.id for r in self._node.graph.frontier()},
            }
            self.on_verification(payload)
            await self._node.gossip.broadcast_verification(payload)
            return

        # Result differs — initiate challenge
        available_verifiers = count_independent_verifiers(
            self._node, record, self.node_id
        )
        if available_verifiers == 0:
            log.warning(
                "Challenge for %s skipped: no independent compatible verifiers in graph",
                record.id[:8],
            )
            return

        log.info(
            "Challenging experiment %s: claimed %.6f, got %.6f",
            record.id[:8],
            record.val_bpb,
            result.val_bpb,
        )
        payload = {
            "event_id": f"challenge:{record.id}:{self.node_id}",
            "experiment_id": record.id,
            "challenger_id": self.node_id,
            "challenger_bpb": result.val_bpb,
            "challenger_gpu": self.gpu_model,
        }
        challenge = PendingChallenge(
            experiment=record,
            challenger_id=self.node_id,
            challenger_bpb=result.val_bpb,
            challenger_gpu=self.gpu_model,
            required_responses=min(VERIFIER_COUNT, available_verifiers),
        )
        self._pending[record.id] = challenge
        self.on_challenge(payload)
        await self._node.gossip.broadcast_challenge(payload)

        # Wait for verifier responses, then resolve
        asyncio.create_task(self._await_resolution(record.id))

    def on_challenge(self, payload: dict):
        """Called when a challenge is received from the network."""
        experiment_id = payload.get("experiment_id", "")
        challenger_gpu = payload.get("challenger_gpu", "")
        challenger_id = payload.get("challenger_id", "")
        event_id = payload.get("event_id", f"challenge:{experiment_id}:{challenger_id}")

        if not self.verifier.reputation.record_event(event_id, "challenge"):
            return

        self.verifier.reputation.verification_performed(challenger_id)

        if not self.verifier.same_gpu_class(challenger_gpu, self.gpu_model):
            return  # Can only verify same GPU class
        if challenger_id == self.node_id:
            return  # Don't verify our own challenges

        record = self._node.graph.get(experiment_id) if self._node else None
        if record is None:
            return
        if record.node_id == self.node_id:
            return  # Original publisher cannot serve as an independent verifier
        if not self.verifier.same_gpu_class(record.gpu_model, self.gpu_model):
            return

        log.info("Volunteering to verify challenge on %s", experiment_id[:8])
        asyncio.create_task(self._run_verification(record, payload))

    async def _run_verification(self, record: ExperimentRecord, challenge: dict):
        """Re-run experiment as a verifier and send response."""
        if self._node is None or self._node.workspace is None:
            return

        code_bytes = await self._get_code_bytes(record)
        if not code_bytes:
            return

        if self._node.training.busy():
            log.info(
                "Queueing verification for %s until local training slot is free",
                record.id[:8],
            )
        result = await self._node.training.run_isolated(
            self._node.workspace, code_bytes.decode("utf-8")
        )

        if not result.success:
            return

        response = {
            "event_id": (
                f"challenge_response:{record.id}:{challenge['challenger_id']}:{self.node_id}"
            ),
            "experiment_id": record.id,
            "challenger_id": challenge["challenger_id"],
            "verifier_id": self.node_id,
            "verifier_bpb": result.val_bpb,
            "verifier_gpu": self.gpu_model,
        }

        # Broadcast response so challenger (and everyone) sees it
        self.on_challenge_response(response)
        await self._node.gossip.broadcast_challenge_response(response)
        log.info(
            "Verification of %s complete: val_bpb=%.6f",
            record.id[:8],
            result.val_bpb,
        )

    def on_challenge_response(self, payload: dict):
        """Collect verifier responses for challenges we initiated."""
        experiment_id = payload.get("experiment_id", "")
        verifier_id = payload.get("verifier_id", "")
        event_id = payload.get(
            "event_id",
            f"challenge_response:{experiment_id}:{payload.get('challenger_id', '')}:{verifier_id}",
        )

        if not self.verifier.reputation.record_event(event_id, "challenge_response"):
            return

        self.verifier.reputation.verification_performed(verifier_id)

        pending = self._pending.get(experiment_id)
        if pending is None:
            return  # Not our challenge
        if pending.challenger_id != self.node_id:
            return
        if verifier_id in pending.responder_id:
            return

        vr = VerificationResult(
            experiment_id=experiment_id,
            verifier_node_id=verifier_id,
            verifier_val_bpb=payload["verifier_bpb"],
            verifier_gpu=payload["verifier_gpu"],
            within_tolerance=False,  # Will be determined in resolution
        )
        pending.response.append(vr)
        pending.responder_id.add(verifier_id)
        log.info(
            "Challenge response %d/%d for %s",
            len(pending.response),
            pending.required_responses,
            experiment_id[:8],
        )

    async def _await_resolution(self, experiment_id: str):
        """Wait for verifier responses, then resolve the dispute."""
        deadline = time.time() + CHALLENGE_TIMEOUT
        while time.time() < deadline:
            pending = self._pending.get(experiment_id)
            if pending is None:
                return
            if len(pending.response) >= pending.required_responses:
                break
            await asyncio.sleep(5)

        pending = self._pending.pop(experiment_id, None)
        if pending is None:
            return

        if not pending.response:
            log.warning("No verifiers responded for challenge on %s", experiment_id[:8])
            return

        # Resolve using median of all results
        dispute = self.verifier.resolve_dispute(
            pending.experiment,
            pending.challenger_bpb,
            pending.challenger_id,
            pending.challenger_gpu,
            pending.response,
        )

        log.info(
            "Dispute resolved for %s: %s (ground_truth=%.6f)",
            experiment_id[:8],
            dispute.outcome.value,
            dispute.ground_truth_bpb,
        )

        # Broadcast dispute result
        if self._node:
            if dispute.outcome == DisputeOutcome.UPHELD:
                self._node.graph.mark_verified(experiment_id, True)
            payload = {
                "event_id": f"dispute:{dispute.experiment_id}:{dispute.challenger_id}",
                "experiment_id": dispute.experiment_id,
                "original_node_id": pending.experiment.node_id,
                "challenger_id": dispute.challenger_id,
                "challenger_bpb": dispute.challenger_bpb,
                "outcome": dispute.outcome.value,
                "ground_truth_bpb": dispute.ground_truth_bpb,
                "verifier_count": len(dispute.verifier_result),
            }
            self.on_dispute(payload)
            await self._node.gossip.broadcast_dispute(payload)

    def on_verification(self, payload: dict):
        """Apply a successful spot-check network-wide."""
        if self._node is None:
            return
        apply_verification_event(self._node, self.verifier, payload)

    def on_dispute(self, payload: dict):
        """Called when a resolved dispute arrives from the network."""
        outcome = payload.get("outcome", "")
        experiment_id = payload.get("experiment_id", "")
        if self._node is None:
            return
        if not apply_dispute_event(self._node, self.verifier, payload):
            return

        log.info(
            "Dispute result for %s: %s (ground_truth=%.6f)",
            experiment_id[:8],
            outcome,
            payload.get("ground_truth_bpb", 0),
        )
        # Clean up if we had a pending challenge for this
        self._pending.pop(experiment_id, None)

    async def _get_code_bytes(self, record: ExperimentRecord) -> bytes | None:
        """Load code locally or fetch it from peers for verification."""
        if self._node is None:
            return None

        code_bytes = self._node.store.get(record.code_cid)
        if code_bytes is not None:
            return code_bytes

        return await self._node.fetch_code(record.code_cid)

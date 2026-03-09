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
from dataclasses import dataclass, field

from .record import ExperimentRecord
from .verify import (
    DisputeOutcome,
    VerificationResult,
    Verifier,
)

log = logging.getLogger(__name__)

VERIFIER_COUNT = 3
CHALLENGE_TIMEOUT = 600  # 10 min to collect verifier responses


@dataclass
class PendingChallenge:
    experiment: ExperimentRecord
    challenger_id: str
    challenger_bpb: float
    challenger_gpu: str
    response: list[VerificationResult] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class ChallengeCoordinator:
    """Manages the challenge/dispute lifecycle over the gossip network."""

    def __init__(self, verifier: Verifier, node_id: str, gpu_model: str):
        self.verifier = verifier
        self.node_id = node_id
        self.gpu_model = gpu_model
        self._pending: dict[str, PendingChallenge] = {}
        self._node = None  # Set by node after init

    def set_node(self, node):
        self._node = node

    def on_experiment_received(self, record: ExperimentRecord):
        """Called when a new experiment arrives. Decides whether to spot-check."""
        if not self.verifier.should_verify(record):
            return
        if record.gpu_model != self.gpu_model:
            return  # Can only verify same GPU class
        log.info("Spot-checking experiment %s...", record.id[:8])
        asyncio.create_task(self._run_spot_check(record))

    async def _run_spot_check(self, record: ExperimentRecord):
        """Re-run an experiment and challenge if result differs."""
        if self._node is None:
            return

        runner = self._get_runner()
        if runner is None:
            return

        # Re-run the experiment with the recorded code
        code_bytes = await self._get_code_bytes(record)
        if not code_bytes:
            log.warning("No code available for spot-check of %s", record.id[:8])
            return

        runner.apply_code(code_bytes.decode("utf-8"))
        result = await asyncio.to_thread(runner.run_training)

        self.verifier.reputation.verification_performed(self.node_id)

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
            self.verifier.reputation.record_verified(
                record.node_id,
                record,
                is_frontier=record.id in {r.id for r in self._node.graph.frontier()},
            )
            self._node.graph.mark_verified(record.id, True)
            return

        # Result differs — initiate challenge
        log.info(
            "Challenging experiment %s: claimed %.6f, got %.6f",
            record.id[:8],
            record.val_bpb,
            result.val_bpb,
        )
        challenge = PendingChallenge(
            experiment=record,
            challenger_id=self.node_id,
            challenger_bpb=result.val_bpb,
            challenger_gpu=self.gpu_model,
        )
        self._pending[record.id] = challenge

        await self._node.gossip.broadcast_challenge(
            {
                "experiment_id": record.id,
                "challenger_id": self.node_id,
                "challenger_bpb": result.val_bpb,
                "challenger_gpu": self.gpu_model,
            }
        )

        # Wait for verifier responses, then resolve
        asyncio.create_task(self._await_resolution(record.id))

    def on_challenge(self, payload: dict):
        """Called when a challenge is received from the network."""
        experiment_id = payload.get("experiment_id", "")
        challenger_gpu = payload.get("challenger_gpu", "")

        if challenger_gpu != self.gpu_model:
            return  # Can only verify same GPU class
        if payload.get("challenger_id") == self.node_id:
            return  # Don't verify our own challenges

        record = self._node.graph.get(experiment_id) if self._node else None
        if record is None:
            return

        log.info("Volunteering to verify challenge on %s", experiment_id[:8])
        asyncio.create_task(self._run_verification(record, payload))

    async def _run_verification(self, record: ExperimentRecord, challenge: dict):
        """Re-run experiment as a verifier and send response."""
        if self._node is None:
            return

        runner = self._get_runner()
        if runner is None:
            return

        code_bytes = await self._get_code_bytes(record)
        if not code_bytes:
            return

        runner.apply_code(code_bytes.decode("utf-8"))
        result = await asyncio.to_thread(runner.run_training)

        if not result.success:
            return

        response = {
            "experiment_id": record.id,
            "challenger_id": challenge["challenger_id"],
            "verifier_id": self.node_id,
            "verifier_bpb": result.val_bpb,
            "verifier_gpu": self.gpu_model,
        }

        # Broadcast response so challenger (and everyone) sees it
        await self._node.gossip.broadcast_challenge_response(response)
        self.verifier.reputation.verification_performed(self.node_id)
        log.info(
            "Verification of %s complete: val_bpb=%.6f",
            record.id[:8],
            result.val_bpb,
        )

    def on_challenge_response(self, payload: dict):
        """Collect verifier responses for challenges we initiated."""
        experiment_id = payload.get("experiment_id", "")
        pending = self._pending.get(experiment_id)
        if pending is None:
            return  # Not our challenge
        if pending.challenger_id != self.node_id:
            return

        vr = VerificationResult(
            experiment_id=experiment_id,
            verifier_node_id=payload["verifier_id"],
            verifier_val_bpb=payload["verifier_bpb"],
            verifier_gpu=payload["verifier_gpu"],
            within_tolerance=False,  # Will be determined in resolution
        )
        pending.response.append(vr)
        log.info(
            "Challenge response %d/%d for %s",
            len(pending.response),
            VERIFIER_COUNT,
            experiment_id[:8],
        )

    async def _await_resolution(self, experiment_id: str):
        """Wait for verifier responses, then resolve the dispute."""
        deadline = time.time() + CHALLENGE_TIMEOUT
        while time.time() < deadline:
            pending = self._pending.get(experiment_id)
            if pending is None:
                return
            if len(pending.response) >= VERIFIER_COUNT:
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
            await self._node.gossip.broadcast_dispute(
                {
                    "experiment_id": dispute.experiment_id,
                    "challenger_id": dispute.challenger_id,
                    "challenger_bpb": dispute.challenger_bpb,
                    "outcome": dispute.outcome.value,
                    "ground_truth_bpb": dispute.ground_truth_bpb,
                    "verifier_count": len(dispute.verifier_result),
                }
            )

    def on_dispute(self, payload: dict):
        """Called when a resolved dispute arrives from the network."""
        outcome = payload.get("outcome", "")
        experiment_id = payload.get("experiment_id", "")
        log.info(
            "Dispute result for %s: %s (ground_truth=%.6f)",
            experiment_id[:8],
            outcome,
            payload.get("ground_truth_bpb", 0),
        )
        if self._node and outcome == DisputeOutcome.UPHELD.value:
            self._node.graph.mark_verified(experiment_id, True)
        # Clean up if we had a pending challenge for this
        self._pending.pop(experiment_id, None)

    def _get_runner(self):
        """Get an ExperimentRunner from the node's workspace."""
        try:
            from .runner import ExperimentRunner

            return ExperimentRunner(self._node.workspace)
        except Exception:
            return None

    async def _get_code_bytes(self, record: ExperimentRecord) -> bytes | None:
        """Load code locally or fetch it from peers for verification."""
        if self._node is None:
            return None

        code_bytes = self._node.store.get(record.code_cid)
        if code_bytes is not None:
            return code_bytes

        return await self._node.fetch_code(record.code_cid)

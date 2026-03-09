"""Tests for Verifier — tolerance bands, reputation, challenges, disputes."""

from test.conftest import make_record

from spore.record import Status
from spore.verify import (
    DEFAULT_TOLERANCE,
    DisputeOutcome,
    VerificationResult,
    Verifier,
)


class TestReputationStore:
    def test_initial_score_is_zero(self, reputation):
        assert reputation.get_score("node_abc") == 0.0

    def test_update_score(self, reputation):
        reputation.update_score("node_abc", 5.0)
        assert reputation.get_score("node_abc") == 5.0

    def test_score_clamps_at_100(self, reputation):
        reputation.update_score("node_abc", 200.0)
        assert reputation.get_score("node_abc") == 100.0

    def test_score_clamps_at_negative_100(self, reputation):
        reputation.update_score("node_abc", -200.0)
        assert reputation.get_score("node_abc") == -100.0

    def test_record_published(self, reputation, keypair):
        _, node_id = keypair
        record = make_record(keypair)
        reputation.record_published(node_id, record)
        stats = reputation.get_stats(node_id)
        assert stats["experiments_published"] == 1
        assert stats["score"] == 0.0  # No score change on publish

    def test_record_verified_keep(self, reputation, keypair):
        _, node_id = keypair
        record = make_record(keypair, status=Status.KEEP)
        reputation.record_verified(node_id, record)
        assert reputation.get_score(node_id) == 1.0

    def test_record_verified_keep_frontier(self, reputation, keypair):
        _, node_id = keypair
        record = make_record(keypair, status=Status.KEEP)
        reputation.record_verified(node_id, record, is_frontier=True)
        assert reputation.get_score(node_id) == 2.0

    def test_record_verified_discard(self, reputation, keypair):
        _, node_id = keypair
        record = make_record(keypair, status=Status.DISCARD)
        reputation.record_verified(node_id, record)
        assert reputation.get_score(node_id) == 0.3

    def test_verification_performed(self, reputation):
        reputation.verification_performed("verifier_1")
        assert reputation.get_score("verifier_1") == 0.5

    def test_dispute_resolved(self, reputation):
        reputation.dispute_resolved("winner", "loser")
        assert reputation.get_score("winner") == 1.0
        assert reputation.get_score("loser") == -5.0

    def test_leaderboard(self, reputation):
        reputation.update_score("alice", 10.0)
        reputation.update_score("bob", 5.0)
        reputation.update_score("charlie", 15.0)
        board = reputation.leaderboard(limit=2)
        assert len(board) == 2
        assert board[0]["node_id"] == "charlie"
        assert board[1]["node_id"] == "alice"

    def test_get_stats(self, reputation, keypair):
        _, node_id = keypair
        record = make_record(keypair, status=Status.KEEP)
        reputation.record_published(node_id, record)
        reputation.record_verified(node_id, record)
        reputation.verification_performed(node_id)

        stats = reputation.get_stats(node_id)
        assert stats["experiments_published"] == 1
        assert stats["experiments_verified"] == 1
        assert stats["verifications_performed"] == 1
        assert stats["score"] == 1.5  # 1.0 (verified keep) + 0.5 (verification)

    def test_backfill_published(self, reputation, keypair, second_keypair):
        _, node_id = keypair
        _, second_node_id = second_keypair
        records = [
            make_record(keypair, description="a"),
            make_record(keypair, description="b"),
            make_record(second_keypair, description="c"),
        ]

        reputation.backfill_published(records)
        reputation.backfill_published(records)  # idempotent

        assert reputation.get_stats(node_id)["experiments_published"] == 2
        assert reputation.get_stats(second_node_id)["experiments_published"] == 1


class TestVerifier:
    def test_tolerance_band(self, reputation):
        verifier = Verifier(reputation)
        assert verifier.get_tolerance("H100-SXM5-80GB") == 0.0015
        assert verifier.get_tolerance("RTX_4090") == 0.002
        assert verifier.get_tolerance("unknown_gpu") == DEFAULT_TOLERANCE

    def test_verify_within_tolerance(self, reputation, keypair):
        verifier = Verifier(reputation)
        record = make_record(keypair, val_bpb=0.95, gpu_model="RTX_4090")
        result = verifier.verify_result(
            record,
            actual_bpb=0.9505,
            verifier_node_id="verifier_1",
            verifier_gpu="RTX_4090",
        )
        assert result.within_tolerance

    def test_verify_outside_tolerance(self, reputation, keypair):
        verifier = Verifier(reputation)
        record = make_record(keypair, val_bpb=0.95, gpu_model="RTX_4090")
        result = verifier.verify_result(
            record,
            actual_bpb=0.96,  # 0.01 diff > 0.002 tolerance
            verifier_node_id="verifier_1",
            verifier_gpu="RTX_4090",
        )
        assert not result.within_tolerance

    def test_cross_gpu_always_passes(self, reputation, keypair):
        """Cross-GPU verification can't compare, so it passes."""
        verifier = Verifier(reputation)
        record = make_record(keypair, val_bpb=0.95, gpu_model="H100-SXM5-80GB")
        result = verifier.verify_result(
            record,
            actual_bpb=1.5,  # Wildly different
            verifier_node_id="verifier_1",
            verifier_gpu="RTX_4090",
        )
        assert result.within_tolerance  # Can't compare

    def test_challenge_valid(self, reputation, keypair):
        verifier = Verifier(reputation)
        record = make_record(keypair, val_bpb=0.95, gpu_model="RTX_4090")
        assert verifier.challenge(
            record,
            challenger_bpb=0.96,
            challenger_id="challenger_1",
            challenger_gpu="RTX_4090",
        )

    def test_challenge_invalid_within_tolerance(self, reputation, keypair):
        verifier = Verifier(reputation)
        record = make_record(keypair, val_bpb=0.95, gpu_model="RTX_4090")
        assert not verifier.challenge(
            record,
            challenger_bpb=0.9505,  # Within tolerance
            challenger_id="challenger_1",
            challenger_gpu="RTX_4090",
        )

    def test_challenge_invalid_cross_gpu(self, reputation, keypair):
        verifier = Verifier(reputation)
        record = make_record(keypair, val_bpb=0.95, gpu_model="H100-SXM5-80GB")
        assert not verifier.challenge(
            record,
            challenger_bpb=1.5,
            challenger_id="challenger_1",
            challenger_gpu="RTX_4090",
        )


class TestDisputeResolution:
    def test_dispute_upheld(self, reputation, keypair):
        """Original was valid, challenger was wrong."""
        verifier = Verifier(reputation)
        _, node_id = keypair
        record = make_record(keypair, val_bpb=0.950, gpu_model="RTX_4090")

        verifier_results = [
            VerificationResult("exp1", f"v{i}", 0.9500 + i * 0.0001, "RTX_4090", True)
            for i in range(3)
        ]

        dispute = verifier.resolve_dispute(
            record,
            challenger_bpb=0.960,  # Challenger got different result
            challenger_id="challenger_1",
            challenger_gpu="RTX_4090",
            verifier_results=verifier_results,
        )

        assert dispute.outcome == DisputeOutcome.UPHELD
        # Original node wins, challenger loses
        assert reputation.get_score(node_id) == 1.0
        assert reputation.get_score("challenger_1") == -5.0

    def test_dispute_rejected(self, reputation, keypair):
        """Original was fabricated."""
        verifier = Verifier(reputation)
        _, node_id = keypair
        record = make_record(keypair, val_bpb=0.900, gpu_model="RTX_4090")

        # All verifiers got ~0.960, original claimed 0.900
        verifier_results = [
            VerificationResult("exp1", f"v{i}", 0.960 + i * 0.0001, "RTX_4090", True)
            for i in range(3)
        ]

        dispute = verifier.resolve_dispute(
            record,
            challenger_bpb=0.960,
            challenger_id="challenger_1",
            challenger_gpu="RTX_4090",
            verifier_results=verifier_results,
        )

        assert dispute.outcome == DisputeOutcome.REJECTED
        # Challenger wins, original node loses
        assert reputation.get_score("challenger_1") == 1.0
        assert reputation.get_score(node_id) == -5.0


class TestSuspiciousCheck:
    def test_normal_record_no_flags(self, reputation, keypair):
        verifier = Verifier(reputation)
        record = make_record(keypair, val_bpb=0.95, gpu_model="RTX_4090")
        flags = verifier.check_suspicious(record)
        assert len(flags) == 0

    def test_zero_bpb_non_crash(self, reputation, keypair):
        verifier = Verifier(reputation)
        record = make_record(
            keypair, val_bpb=0.0, status=Status.KEEP, gpu_model="RTX_4090"
        )
        flags = verifier.check_suspicious(record)
        assert any("zero_bpb" in f for f in flags)

    def test_suspiciously_low_bpb(self, reputation, keypair):
        verifier = Verifier(reputation)
        record = make_record(keypair, val_bpb=0.1, gpu_model="RTX_4090")
        flags = verifier.check_suspicious(record)
        assert any("suspiciously_low" in f for f in flags)

    def test_vram_exceeds_gpu(self, reputation, keypair):
        from spore.record import ExperimentRecord

        sk, node_id = keypair
        record = ExperimentRecord(
            parent=None,
            depth=0,
            code_cid="a" * 64,
            diff="",
            dataset_cid="d",
            prepare_cid="p",
            time_budget=300,
            val_bpb=0.95,
            peak_vram_mb=30000,  # 30GB > 24GB for RTX 4090
            num_steps=500,
            num_params=124_000_000,
            status=Status.KEEP,
            description="",
            hypothesis="",
            agent_model="test",
            gpu_model="RTX_4090",
            cuda_version="12.4",
            torch_version="2.5.1",
            node_id=node_id,
        )
        record.sign(sk)

        verifier = Verifier(reputation)
        flags = verifier.check_suspicious(record)
        assert any("vram_exceeds" in f for f in flags)


class TestShouldVerify:
    def test_spot_check_rate(self, reputation, keypair):
        """With 100% rate, always verify."""
        verifier = Verifier(reputation, spot_check_rate=1.0)
        record = make_record(keypair)
        assert verifier.should_verify(record)

    def test_zero_rate_never_verifies(self, reputation, keypair):
        """With 0% rate, never verify."""
        verifier = Verifier(reputation, spot_check_rate=0.0)
        record = make_record(keypair)
        assert not verifier.should_verify(record)

    def test_low_rep_increases_rate(self, reputation, keypair):
        """Low reputation nodes are verified more often."""
        _, node_id = keypair
        reputation.update_score(node_id, -10.0)

        verifier = Verifier(reputation, spot_check_rate=0.1)
        record = make_record(keypair)

        # Run many times, count verifications
        verified = sum(1 for _ in range(1000) if verifier.should_verify(record))
        # Should be around 30% (3x base rate), not 10%
        assert verified > 200  # At least 20%

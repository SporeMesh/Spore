"""Tests for ExperimentRunner — training execution and result parsing."""

from test.conftest import make_record

import pytest

from spore.record import Status
from spore.runner import ExperimentRunner, TrainResult


class TestParseOutput:
    def test_parse_complete_output(self):
        runner = ExperimentRunner("/tmp")
        output = """
step 100
step 200
step 500
num_parameters: 124,000,000
peak_vram_mb: 24000.0
val_bpb: 0.972345
"""
        result = runner._parse_output(output)
        assert result.val_bpb == pytest.approx(0.972345)
        assert result.peak_vram_mb == 24000.0
        assert result.num_params == 124_000_000
        assert result.num_steps == 500  # Last step

    def test_parse_empty_output(self):
        runner = ExperimentRunner("/tmp")
        result = runner._parse_output("")
        assert result.val_bpb == 0.0
        assert result.num_steps == 0

    def test_parse_partial_output(self):
        runner = ExperimentRunner("/tmp")
        result = runner._parse_output("val_bpb: 0.95\nstep 100")
        assert result.val_bpb == 0.95
        assert result.num_steps == 100
        assert result.peak_vram_mb == 0.0

    def test_parse_workspace_summary_output(self):
        runner = ExperimentRunner("/tmp")
        output = """
step 100
num_steps:        307
num_params_M:     124.0
peak_vram_mb:     11701.0
val_bpb:          1.103047
"""
        result = runner._parse_output(output)
        assert result.val_bpb == pytest.approx(1.103047)
        assert result.peak_vram_mb == 11701.0
        assert result.num_params == 124_000_000
        assert result.num_steps == 307


class TestRunTraining:
    def test_run_stub(self, tmp_path):
        """Run the training stub and verify output parsing."""
        # Copy the stub to workspace
        stub_code = """
import hashlib
import sys
import time

code = open(__file__).read()
code_hash = int(hashlib.sha256(code.encode()).hexdigest()[:8], 16)
base_bpb = 0.95 + (code_hash % 1000) / 10000
time.sleep(0.05)
num_steps = 500

print(f"step {num_steps}")
print(f"num_parameters: 124,000,000")
print(f"peak_vram_mb: 24000.0")
print(f"val_bpb: {base_bpb:.6f}")
"""
        train_script = tmp_path / "train.py"
        train_script.write_text(stub_code)

        runner = ExperimentRunner(tmp_path, time_budget=10)
        result = runner.run_training()

        assert result.success
        assert result.val_bpb > 0
        assert result.num_steps == 500
        assert result.num_params == 124_000_000
        assert result.peak_vram_mb == 24000.0
        assert result.training_sec > 0

    def test_run_crash(self, tmp_path):
        """Training script that crashes."""
        train_script = tmp_path / "train.py"
        train_script.write_text("raise RuntimeError('boom')")

        runner = ExperimentRunner(tmp_path, time_budget=10)
        result = runner.run_training()

        assert not result.success
        assert result.val_bpb == 0.0

    def test_run_missing_script(self, tmp_path):
        runner = ExperimentRunner(tmp_path, time_budget=10)
        result = runner.run_training("nonexistent.py")
        assert not result.success
        assert "not found" in result.error


class TestMakeRecord:
    def test_make_record_keep(self, tmp_path, keypair):
        train_script = tmp_path / "train.py"
        train_script.write_text("# baseline")

        runner = ExperimentRunner(tmp_path)
        parent = make_record(keypair, val_bpb=1.0)
        result = TrainResult(val_bpb=0.95, success=True)
        _, node_id = keypair

        record = runner.make_record(
            result,
            parent=parent,
            diff="- old\n+ new",
            description="improved",
            hypothesis="should work",
            agent_model="test",
            dataset_cid="d",
            prepare_cid="p",
            node_id=node_id,
        )

        assert record.status == Status.KEEP
        assert record.val_bpb == 0.95
        assert record.parent == parent.id
        assert record.depth == 1

    def test_make_record_discard(self, tmp_path, keypair):
        train_script = tmp_path / "train.py"
        train_script.write_text("# baseline")

        runner = ExperimentRunner(tmp_path)
        parent = make_record(keypair, val_bpb=0.90)
        result = TrainResult(val_bpb=0.95, success=True)  # Worse than parent
        _, node_id = keypair

        record = runner.make_record(
            result,
            parent=parent,
            diff="- old\n+ new",
            description="regression",
            hypothesis="didnt work",
            agent_model="test",
            dataset_cid="d",
            prepare_cid="p",
            node_id=node_id,
        )

        assert record.status == Status.DISCARD

    def test_make_record_crash(self, tmp_path, keypair):
        train_script = tmp_path / "train.py"
        train_script.write_text("# baseline")

        runner = ExperimentRunner(tmp_path)
        result = TrainResult(val_bpb=0.0, success=False, error="OOM")
        _, node_id = keypair

        record = runner.make_record(
            result,
            parent=None,
            diff="",
            description="crashed",
            hypothesis="",
            agent_model="test",
            dataset_cid="d",
            prepare_cid="p",
            node_id=node_id,
        )

        assert record.status == Status.CRASH

    def test_make_genesis_record(self, tmp_path, keypair):
        train_script = tmp_path / "train.py"
        train_script.write_text("# genesis")

        runner = ExperimentRunner(tmp_path)
        result = TrainResult(val_bpb=1.0, success=True)
        _, node_id = keypair

        record = runner.make_record(
            result,
            parent=None,
            diff="",
            description="genesis",
            hypothesis="baseline",
            agent_model="test",
            dataset_cid="d",
            prepare_cid="p",
            node_id=node_id,
        )

        assert record.parent is None
        assert record.depth == 0
        assert record.status == Status.KEEP


class TestCodeManagement:
    def test_apply_and_get_code(self, tmp_path):
        runner = ExperimentRunner(tmp_path)
        runner.apply_code("print('hello')")
        assert runner.get_code() == "print('hello')"

    def test_code_cid_changes(self, tmp_path):
        runner = ExperimentRunner(tmp_path)
        runner.apply_code("version_1")
        cid1 = runner.get_code_cid()
        runner.apply_code("version_2")
        cid2 = runner.get_code_cid()
        assert cid1 != cid2

    def test_code_cid_deterministic(self, tmp_path):
        runner = ExperimentRunner(tmp_path)
        runner.apply_code("same content")
        cid1 = runner.get_code_cid()
        runner.apply_code("same content")
        cid2 = runner.get_code_cid()
        assert cid1 == cid2

"""Tests for local proposal validation policy."""

from __future__ import annotations

from spore.proposal_policy import validate_candidate_code

BASE_CODE = """
from prepare import MAX_SEQ_LEN, TIME_BUDGET, Tokenizer, evaluate_bpb, make_dataloader
TOTAL_BATCH_SIZE = 2**19
ASPECT_RATIO = 64
HEAD_DIM = 128
DEPTH = 8
print("val_bpb: 1.0")
print("num_steps: 10")
print("peak_vram_mb: 100")
"""


def test_rejects_bad_seq_len_name(monkeypatch):
    monkeypatch.setattr("spore.proposal_policy.is_constrained_runtime", lambda: True)
    code = BASE_CODE.replace("MAX_SEQ_LEN", "MAX_SEQ_SIZE", 1)

    errors = validate_candidate_code(code, BASE_CODE)

    assert "use MAX_SEQ_LEN, not MAX_SEQ_SIZE" in errors


def test_rejects_oversized_depth_on_constrained_runtime(monkeypatch):
    monkeypatch.setattr("spore.proposal_policy.is_constrained_runtime", lambda: True)
    code = BASE_CODE.replace("DEPTH = 8", "DEPTH = 10")

    errors = validate_candidate_code(code, BASE_CODE)

    assert any("DEPTH must stay <=" in error for error in errors)


def test_rejects_larger_model_dim_on_constrained_runtime(monkeypatch):
    monkeypatch.setattr("spore.proposal_policy.is_constrained_runtime", lambda: True)
    code = BASE_CODE.replace("ASPECT_RATIO = 64", "ASPECT_RATIO = 96")

    errors = validate_candidate_code(code, BASE_CODE)

    assert any("DEPTH*ASPECT_RATIO must stay <=" in error for error in errors)


def test_rejects_new_compile_sites(monkeypatch):
    monkeypatch.setattr("spore.proposal_policy.is_constrained_runtime", lambda: False)
    code = BASE_CODE + "\nmodel = torch.compile(model)\n"

    errors = validate_candidate_code(code, BASE_CODE)

    assert "do not add new torch.compile call sites" in errors

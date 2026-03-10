"""Tests for GPU/backend normalization."""

from spore.gpu import gpu_verification_class, normalize_gpu_model


def test_normalize_nvidia_model():
    assert normalize_gpu_model("NVIDIA GeForce RTX 3060") == "RTX_3060"
    assert gpu_verification_class("NVIDIA_GeForce_RTX_5090") == "RTX_5090"


def test_normalize_mps_and_cpu():
    assert normalize_gpu_model("Apple MPS") == "APPLE_MPS"
    assert gpu_verification_class("apple mps") == "APPLE_MPS"
    assert normalize_gpu_model("cpu") == "CPU"

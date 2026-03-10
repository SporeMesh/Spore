"""Tests for local compile disable policy."""

from spore.compile_policy import compile_env_overrides


def test_compile_env_overrides_default_shape():
    overrides = compile_env_overrides()
    assert isinstance(overrides, dict)
    if overrides:
        assert overrides["SPORE_DISABLE_COMPILE"] == "1"
        assert "SPORE_DISABLE_COMPILE_REASON" in overrides

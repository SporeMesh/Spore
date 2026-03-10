"""Local policy for enabling or disabling torch.compile."""

from __future__ import annotations


def compile_disabled_reason() -> str | None:
    """Return a reason to disable compile on the current machine, if any."""
    try:
        import torch
    except ImportError:
        return None

    if not torch.cuda.is_available():
        return None

    props = torch.cuda.get_device_properties(0)
    total_memory_gb = props.total_memory / (1024**3)
    sm_count = props.multi_processor_count

    if total_memory_gb < 16:
        return f"cuda_gpu_memory_lt_16gb:{total_memory_gb:.1f}GB"
    if sm_count < 48:
        return f"cuda_sm_count_lt_48:{sm_count}"

    return None


def compile_env_overrides() -> dict[str, str]:
    """Environment overrides for stable training on the current machine."""
    reason = compile_disabled_reason()
    if not reason:
        return {}
    return {
        "SPORE_DISABLE_COMPILE": "1",
        "TORCHINDUCTOR_COMPILE_THREADS": "1",
        "SPORE_DISABLE_COMPILE_REASON": reason,
    }

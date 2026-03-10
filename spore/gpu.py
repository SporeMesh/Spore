"""GPU model normalization for verification and tolerance matching."""

from __future__ import annotations

import re


def normalize_gpu_model(gpu_model: str | None) -> str:
    """Return a stable GPU identifier from provider-specific device strings."""
    if not gpu_model:
        return "UNKNOWN"

    normalized = gpu_model.strip().replace("-", "_").replace(" ", "_").upper()
    normalized = re.sub(r"_+", "_", normalized)

    if "MPS" in normalized or "APPLE" in normalized:
        return "APPLE_MPS"
    if normalized in {"CPU", "UNKNOWN"}:
        return normalized

    if normalized.startswith("H100"):
        return "H100"
    if normalized.startswith("A100"):
        return "A100"

    for family in ("RTX", "GTX"):
        match = re.search(rf"{family}_?(\d{{3,4}})", normalized)
        if match:
            return f"{family}_{match.group(1)}"

    return normalized


def gpu_verification_class(gpu_model: str | None) -> str:
    """Collapse model strings into the class used for challenge compatibility."""
    normalized = normalize_gpu_model(gpu_model)

    if normalized.startswith("RTX_"):
        return normalized
    if normalized.startswith("GTX_"):
        return normalized
    if normalized.startswith("H100"):
        return "H100"
    if normalized.startswith("A100"):
        return "A100"

    return normalized

from __future__ import annotations

import os
import platform
import socket
import subprocess
import sys
from typing import Any


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _detect_gpu_model() -> str:
    nvidia = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if nvidia:
        return nvidia.splitlines()[0].strip()
    if sys.platform == "darwin":
        metal = _run(["system_profiler", "SPDisplaysDataType"])
        if metal:
            for line in metal.splitlines():
                if "Chipset Model:" in line:
                    return line.split(":", 1)[1].strip()
    return ""


def _detect_memory_gb() -> int | None:
    if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
        try:
            pages = int(os.sysconf("SC_PHYS_PAGES"))
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            return max(1, round((pages * page_size) / (1024**3)))
        except Exception:
            return None
    return None


def detect_node_profile() -> dict[str, Any]:
    hostname = socket.gethostname().split(".")[0]
    return {
        "label": hostname,
        "gpu_model": _detect_gpu_model(),
        "cpu_model": platform.processor() or platform.machine(),
        "memory_gb": _detect_memory_gb(),
        "platform": platform.platform(),
        "software_version": "",
        "metadata_jsonb": {
            "hostname": hostname,
            "python_version": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
    }

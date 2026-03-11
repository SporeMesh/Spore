#!/usr/bin/env python3
"""Generate the release manifest consumed by the auto-operator."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: generate_release_manifest.py <version>", file=sys.stderr)
        return 1

    version = sys.argv[1].strip()
    manifest = {
        "version": version,
        "pip_spec": f"sporemesh=={version}",
        "instructions": ["copy_workspace", "backfill_tasks"],
        "notes": f"Release {version}",
    }
    target = Path("release-manifest.json")
    target.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {target} for version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

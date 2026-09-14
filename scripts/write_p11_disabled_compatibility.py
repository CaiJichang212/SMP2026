#!/usr/bin/env python3
"""Write a reviewed manifest for disabled P11 wiring over qualified P9."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_submission import INLINE_MODULES
from starnet.policy.p11_qualification import (
    P11_CERTIFIED_MODE, P11_GATE_REPORT_RELATIVE_PATH, P11_GATE_REPORT_SHA256,
    qualified_p11_mode,
)


P9_MANIFEST = ROOT / "experiments/manifests/p8-release-sources-20260913.json"
P9_REPORT = ROOT / "experiments/reports/p9-bounded-release-result-20260913.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if (P11_CERTIFIED_MODE is not None or P11_GATE_REPORT_SHA256 is not None
            or P11_GATE_REPORT_RELATIVE_PATH is not None
            or qualified_p11_mode("prompt_learning") is not None):
        raise RuntimeError("P11 must be disabled while writing compatibility evidence")
    old = json.loads(P9_MANIFEST.read_text())
    allowed_shell = {
        "src/starnet/submission/starnet_model.py",
        "src/starnet/submission/config.json",
    }
    for relative, expected in old["files"].items():
        if relative not in allowed_shell and sha(ROOT / relative) != expected:
            raise RuntimeError(f"P9 core changed outside disabled P11 wiring: {relative}")
    paths = set(INLINE_MODULES) | {"src/starnet/submission/config.json"}
    paths.update(str(path.relative_to(ROOT))
                 for path in (ROOT / "src/starnet/submission/prompt").glob("*.txt"))
    result = {
        "schema_version": 1,
        "p11_qualification_default": "disabled",
        "p9_gate_report_sha256": sha(P9_REPORT),
        "p9_source_manifest_sha256": sha(P9_MANIFEST),
        "allowed_existing_shell_changes": sorted(allowed_shell),
        "p9_core_files_unchanged": True,
        "p11_activation_smoke": "tests.unit.test_p11_canonical_activation",
        "files": {relative: sha(ROOT / relative) for relative in sorted(paths)},
    }
    output = ROOT / "experiments/manifests/p11-disabled-p9-compatibility-20260914.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(output.relative_to(ROOT)),
                      "files": len(paths), "sha256": sha(output)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

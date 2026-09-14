#!/usr/bin/env python3
"""Finalize the independent P11 source manifest after metadata activation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.build_submission import INLINE_MODULES
from scripts.p11_release_common import qualification_structure, sha256
from starnet.policy.p11_qualification import (
    P11_CERTIFIED_MODE, P11_GATE_REPORT_RELATIVE_PATH, P11_GATE_REPORT_SHA256,
    qualified_p11_mode,
)


QUALIFICATION = "src/starnet/policy/p11_qualification.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activation-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=(
        ROOT / "experiments/manifests/p11-release-sources-20260914.json"
    ))
    args = parser.parse_args()
    if (qualified_p11_mode(P11_CERTIFIED_MODE) != "prompt_learning"
            or args.activation_report.resolve()
            != (ROOT / str(P11_GATE_REPORT_RELATIVE_PATH)).resolve()
            or sha256(args.activation_report) != P11_GATE_REPORT_SHA256):
        raise ValueError("current P11 metadata does not point at this activation report")
    evidence = json.loads(args.activation_report.read_text())
    if (evidence.get("activation_seal_passed") is not True
            or evidence.get("unreleased_entry_gate_passed") is not True):
        raise ValueError("P11 activation report is not sealed")
    historical = subprocess.check_output(
        ["git", "show", f"{evidence['validated_commit']}:{QUALIFICATION}"], cwd=ROOT,
    ).decode()
    current = (ROOT / QUALIFICATION).read_text()
    if qualification_structure(current) != qualification_structure(historical):
        raise ValueError("P11 qualification changed outside metadata")
    paths = set(INLINE_MODULES) | {"src/starnet/submission/config.json"}
    paths.update(str(path.relative_to(ROOT))
                 for path in (ROOT / "src/starnet/submission/prompt").glob("*.txt"))
    if set(evidence.get("source_snapshot", {})) != paths:
        raise ValueError("sealed P11 source snapshot has incomplete coverage")
    for relative, expected in evidence["source_snapshot"].items():
        if relative != QUALIFICATION and sha256(ROOT / relative) != expected:
            raise ValueError(f"P11 strategy changed after seal: {relative}")
    result = {
        "schema_version": 1,
        "activation_report_path": str(args.activation_report.resolve().relative_to(ROOT)),
        "activation_report_sha256": P11_GATE_REPORT_SHA256,
        "validated_unreleased_model_sha256": evidence["validated_unreleased_model_sha256"],
        "qualification_metadata_only": True,
        "files": {relative: sha256(ROOT / relative) for relative in sorted(paths)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output.resolve().relative_to(ROOT)),
                      "files": len(paths), "sha256": sha256(args.output)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Seal P11 activation metadata after statistical and unreleased-entry gates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.build_submission import INLINE_MODULES, assemble_model
from scripts.p11_release_common import sha256, validate_prompt_entry


QUALIFICATION = "src/starnet/policy/p11_qualification.py"
PROTOCOL = ROOT / "experiments/manifests/p11-full-policy-validation-20260914.json"


def expected_runtime_paths() -> set[str]:
    paths = set(INLINE_MODULES) | {"src/starnet/submission/config.json"}
    paths.update(str(path.relative_to(ROOT))
                 for path in (ROOT / "src/starnet/submission/prompt").glob("*.txt"))
    return paths


def seal(development, confirmation, real_entry, py39_entry, modern_entry,
         *, validated_commit: str):
    protocol_sha256 = sha256(PROTOCOL)
    if (development.get("protocol_sha256") != protocol_sha256
            or confirmation.get("protocol_sha256") != protocol_sha256
            or development.get("cases") != 252
            or confirmation.get("cases") != 360):
        raise ValueError("P11 evidence does not match the frozen full-policy protocol")
    if (development.get("development_gate_passed") is not True
            or development.get("selected_variant") != "prompt_learning"):
        raise ValueError("P11 development did not select prompt learning")
    if (confirmation.get("statistical_gate_passed") is not True
            or confirmation.get("selected_variant") != "prompt_learning"):
        raise ValueError("P11 confirmation did not pass its frozen gate")
    snapshot = confirmation.get("source_snapshot")
    if (not isinstance(snapshot, dict) or development.get("source_snapshot") != snapshot
            or set(snapshot) != expected_runtime_paths() or QUALIFICATION not in snapshot):
        raise ValueError("P11 evidence does not cover one frozen canonical runtime")
    for relative, expected in snapshot.items():
        if sha256(ROOT / relative) != expected:
            raise ValueError(f"P11 runtime changed after confirmation: {relative}")
    historical = subprocess.check_output(
        ["git", "show", f"{validated_commit}:{QUALIFICATION}"], cwd=ROOT,
    )
    if hashlib.sha256(historical).hexdigest() != snapshot[QUALIFICATION]:
        raise ValueError("validated commit does not contain the confirmed P11 qualification blob")
    model_hash = hashlib.sha256(assemble_model().encode("utf-8")).hexdigest()
    normalized_entries = [
        validate_prompt_entry(entry, model_hash)
        for entry in (real_entry, py39_entry, modern_entry)
    ]
    real_entry, py39_entry, modern_entry = normalized_entries
    for entry in normalized_entries:
        if entry.get("unreleased_candidate_assembly") is not True:
            raise ValueError("activation seal requires unreleased assembly evidence")
    if (real_entry.get("llm_mode") != "real" or real_entry.get("llm_accepted", 0) <= 0
            or real_entry.get("environment") != "public custom-seed sandbox"
            or real_entry.get("public_response_error") != 0
            or real_entry.get("transport_errors") != 0):
        raise ValueError("missing real LLM/public P11 entry evidence")
    if (not py39_entry.get("python_version", "").startswith("3.9.")
            or py39_entry.get("networkx_version") != "3.1"
            or not py39_entry.get("framework_model_module", "").startswith(("casevo.", "agent_mesa."))
            or py39_entry.get("action_sha256") != modern_entry.get("action_sha256")
            or py39_entry.get("score") != modern_entry.get("score")):
        raise ValueError("P11 target interpreter evidence differs from modern execution")
    try:
        modern_version = tuple(int(part) for part in modern_entry["python_version"].split(".")[:2])
    except (KeyError, TypeError, ValueError):
        modern_version = ()
    if (modern_version < (3, 11)
            or not modern_entry.get("framework_model_module", "").startswith(("casevo.", "agent_mesa."))):
        raise ValueError("P11 modern framework execution is missing")
    if len({entry.get("seed_sha256") for entry in (real_entry, py39_entry, modern_entry)}) != 1:
        raise ValueError("P11 entry checks used different seeds")
    if real_entry.get("p11_selected_prompt_id") == 1:
        raise ValueError("real P11 entry did not demonstrate prompt-ID learning")

    result = dict(confirmation)
    result.update({
        "selected_variant": "prompt_learning",
        "activation_seal_passed": True,
        "unreleased_entry_gate_passed": True,
        "release_gate_passed": False,
        "release_gate_pending": ["final ZIP byte identity", "final ZIP execution"],
        "validated_unreleased_model_sha256": model_hash,
        "validated_commit": validated_commit,
        "qualification_scope": "P11 prompt learning only; P9 evidence and metadata remain independent",
        "research_overlay_note": "Unreleased research assembly evidence is not final-ZIP execution evidence.",
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("development", "confirmation", "real-entry", "py39-entry",
                 "modern-entry", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--validated-commit", required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in (
        "development", "confirmation", "real_entry", "py39_entry", "modern_entry",
    )}
    result = seal(**{name: json.loads(path.read_text()) for name, path in paths.items()},
                  validated_commit=args.validated_commit)
    result["activation_evidence_sha256"] = {
        str(path): sha256(path) for path in paths.values()
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"activation_seal_passed": True,
                      "report_sha256": sha256(args.output)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Seal a measured candidate only after statistical and entry evidence pass."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from scripts.build_submission import assemble_model


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(development, confirmation, real_entry, py39_entry, modern_entry):
    if (development["pairs"] != 56 or development["cohort"] != "development"
            or not development["public_history_resource_audit_passed"]
            or not development["uncapped_score_equivalence"]
            or development["primary"]["mean"] <= 0):
        raise ValueError("development evidence is incomplete or inconsistent")
    if (confirmation["pairs"] != 84 or confirmation["cohort"] != "confirmation"
            or confirmation["statistical_gate_passed"] is not True):
        raise ValueError("confirmation did not pass its frozen gate")
    snapshot = confirmation["source_snapshot"]
    if development["source_snapshot"] != snapshot:
        raise ValueError("development and confirmation used different runtime sources")
    for relative, expected in snapshot.items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f"runtime changed after confirmation: {relative}")
    model_hash = hashlib.sha256(assemble_model().encode("utf-8")).hexdigest()
    for entry in (real_entry, py39_entry, modern_entry):
        if (entry.get("complete") is not True or entry.get("entry_gate_passed") is not True
                or entry.get("model_sha256") != model_hash
                or not entry.get("bounded_estimator_active")
                or entry.get("action_failures") or entry.get("p8_planning_errors")):
            raise ValueError("entry evidence is incomplete, stale, or failed")
    if (real_entry["llm_mode"] != "real" or real_entry["llm_accepted"] <= 0
            or real_entry["environment"] != "public custom-seed sandbox"
            or real_entry["public_response_error"] != 0):
        raise ValueError("missing actual LLM/public-environment execution")
    if (not py39_entry.get("python_version", "").startswith("3.9.")
            or py39_entry.get("networkx_version") != "3.1"
            or not py39_entry.get("framework_model_module", "").startswith(("casevo.", "agent_mesa."))
            or py39_entry["actions_sha256"] != modern_entry["actions_sha256"]
            or py39_entry["score"] != modern_entry["score"]):
        raise ValueError("target interpreter/framework execution is unverified or differs")
    if len({entry["seed_sha256"] for entry in (real_entry, py39_entry, modern_entry)}) != 1:
        raise ValueError("entry checks did not use the same development seed")
    result = dict(confirmation)
    result["variants"] = {"conservative": {"mean_score_gate_passed": True}}
    result["selected_variant"] = "conservative"
    result["release_gate_pending"] = None
    result["release_gate_passed"] = True
    result["qualification_scope"] = "bounded P8 on the declared 50-node, 100-budget paired cohorts; not an official-score estimate"
    result["validated_unreleased_model_sha256"] = model_hash
    result["activation_metadata_note"] = "Report pointer/hash and the source-review manifest are updated after this seal. Strategy bodies must remain identical. The final ZIP is checked separately to avoid self-referential hashes."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("development", "confirmation", "real-entry", "py39-entry", "modern-entry", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("development", "confirmation", "real_entry", "py39_entry", "modern_entry")}
    result = seal(**{name: json.loads(path.read_text()) for name, path in paths.items()})
    result["release_evidence_sha256"] = {str(path): sha(path) for path in paths.values()}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"release_gate_passed": True, "report_sha256": sha(args.output)}))


if __name__ == "__main__":
    main()

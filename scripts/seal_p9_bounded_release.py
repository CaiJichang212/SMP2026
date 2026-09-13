#!/usr/bin/env python3
"""Seal a measured candidate only after statistical and entry evidence pass."""
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
from starnet.experiments.p9_distribution_seeds import FAMILIES, seed_payload


PROTOCOL = ROOT / "experiments/manifests/p9-bounded-release-protocol-20260913.json"
ENTRY_RUNNER = ROOT / "scripts/check_p9_bounded_entry.py"
LEGACY_ENTRY_RUNNER_COMMIT = "1d6a837"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_sha(seed):
    return hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest()


def historical_entry_runner(commit=LEGACY_ENTRY_RUNNER_COMMIT):
    source = subprocess.check_output(
        ["git", "show", f"{commit}:scripts/check_p9_bounded_entry.py"],
        cwd=ROOT,
    )
    return {
        "commit": commit,
        "sha256": hashlib.sha256(source).hexdigest(),
        "legacy_reports_omit_runner_hash": True,
        "revision_association": "recorded after execution from session tool history; not a contemporaneous embedded hash",
    }


def expected_runtime_paths():
    paths = set(INLINE_MODULES) | {"src/starnet/submission/config.json"}
    paths.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/starnet/submission/prompt").glob("*.txt")
    )
    return paths


def seal(development, confirmation, real_entry, py39_entry, modern_entry):
    protocol_sha256 = sha(PROTOCOL)
    if (development.get("protocol_sha256") != protocol_sha256
            or confirmation.get("protocol_sha256") != protocol_sha256):
        raise ValueError("analysis does not match the frozen bounded-release protocol")
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
    if set(snapshot) != expected_runtime_paths():
        raise ValueError("release snapshot does not cover the complete runtime")
    for relative, expected in snapshot.items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f"runtime changed after confirmation: {relative}")
    model_hash = hashlib.sha256(assemble_model().encode("utf-8")).hexdigest()
    for entry in (real_entry, py39_entry, modern_entry):
        if (entry.get("complete") is not True or entry.get("entry_gate_passed") is not True
                or entry.get("model_sha256") != model_hash
                or entry.get("bounded_estimator_active") is not True
                or entry.get("unreleased_candidate_assembly") is not True
                or entry.get("p8_mode") != "conservative"
                or entry.get("transport_errors")
                or entry.get("action_failures") or entry.get("p8_planning_errors")):
            raise ValueError("entry evidence is incomplete, stale, or failed")
        runner_hash = entry.get("entry_runner_sha256")
        if runner_hash is not None and runner_hash != sha(ENTRY_RUNNER):
            raise ValueError("entry evidence used a different checker version")
    if (real_entry["llm_mode"] != "real" or real_entry["llm_accepted"] <= 0
            or real_entry["environment"] != "public custom-seed sandbox"
            or real_entry["public_response_error"] != 0):
        raise ValueError("missing actual LLM/public-environment execution")
    if (not py39_entry.get("python_version", "").startswith("3.9.")
            or py39_entry.get("networkx_version") != "3.1"
            or not py39_entry.get("framework_model_module", "").startswith(("casevo.", "agent_mesa."))
            or py39_entry.get("environment") != "corrected local simulator"
            or py39_entry.get("llm_mode") != "forced_exception_fallback"
            or py39_entry["actions_sha256"] != modern_entry["actions_sha256"]
            or py39_entry["score"] != modern_entry["score"]):
        raise ValueError("target interpreter/framework execution is unverified or differs")
    try:
        modern_version = tuple(int(part) for part in modern_entry.get("python_version", "").split(".")[:2])
    except ValueError:
        modern_version = ()
    if (modern_version < (3, 11)
            or modern_entry.get("python_version", "").startswith("3.9.")
            or not modern_entry.get("networkx_version")
            or not modern_entry.get("framework_model_module", "").startswith(("casevo.", "agent_mesa."))
            or modern_entry.get("environment") != "corrected local simulator"
            or modern_entry.get("llm_mode") != "forced_exception_fallback"):
        raise ValueError("modern interpreter/framework execution is unverified")
    axes = {
        (entry.get("family"), entry.get("repetition"), entry.get("shift"))
        for entry in (real_entry, py39_entry, modern_entry)
    }
    if len(axes) != 1:
        raise ValueError("entry checks did not use the same development seed")
    family, repetition, shift = axes.pop()
    if family not in FAMILIES or repetition not in (901, 902) or shift != "saturated_hubs":
        raise ValueError("entry checks did not use a saturated development seed")
    expected_seed_sha = seed_sha(seed_payload(family, repetition, shift))
    if any(entry.get("seed_sha256") != expected_seed_sha
           for entry in (real_entry, py39_entry, modern_entry)):
        raise ValueError("entry seed hash does not match its declared saturated case")
    result = dict(confirmation)
    result["variants"] = {"conservative": {"mean_score_gate_passed": True}}
    result["selected_variant"] = "conservative"
    result["release_gate_pending"] = None
    result["release_gate_passed"] = True
    result["qualification_scope"] = "bounded P8 on the declared 50-node, 100-budget paired cohorts; not an official-score estimate"
    result["validated_unreleased_model_sha256"] = model_hash
    result["entry_runner_evidence"] = {
        "current_sha256": sha(ENTRY_RUNNER),
        "historical_execution_tool": historical_entry_runner(),
        "interpreter_replay_tool": historical_entry_runner("63049c5"),
    }
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

#!/usr/bin/env python3
"""Screen the P11 response anchor against audited cached original-P11 controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.analyze_p11_full_policy_validation import (
    analyze as analyze_full_policy,
    audit_episode,
    topology_block,
)
from scripts.run_p11_prior_discount_full import evaluate_gate, response_group, summarize
from scripts.run_p11_response_anchor_search import run_arm
from scripts.run_p11_full_policy_validation import json_digest
from starnet.experiments.p11_validation_seeds import development_cases


PROTOCOL = ROOT / "experiments/manifests/p11-anchor-full-development-20260914.json"
ANCHOR_SOURCE = ROOT / "src/starnet/runtime/p11_response_anchor_experiment.py"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def validate_control_audit(audit, control_path, analysis):
    if (audit.get("cohort") != "development" or audit.get("cases") != 252
            or audit.get("input_sha256") != digest(control_path)
            or audit.get("source_snapshot") != analysis.get("source_snapshot")
            or audit.get("identification_passed") is not True
            or audit.get("resource_audit_passed") is not True
            or audit.get("calibration_audit_passed") is not True):
        raise ValueError("original-P11 control audit is incomplete or stale")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--control-audit", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    control = json.loads(args.control.read_text())
    analysis = analyze_full_policy(control, confirmation=False)
    audit = json.loads(args.control_audit.read_text())
    validate_control_audit(audit, args.control, analysis)
    cases = list(development_cases())
    controls = {row["case_id"]: row for row in control["rows"]}
    config = {
        "protocol_sha256": digest(PROTOCOL), "runner_sha256": digest(Path(__file__)),
        "anchor_source_sha256": digest(ANCHOR_SOURCE),
        "control_path": str(args.control), "control_sha256": digest(args.control),
        "control_audit_path": str(args.control_audit),
        "control_audit_sha256": digest(args.control_audit),
        "control_protocol_sha256": analysis["protocol_sha256"],
        "control_source_snapshot": analysis["source_snapshot"],
        "cases": len(cases), "workers": 1, "confirmation_opened": False,
    }
    progress = args.raw_output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("P11 anchor progress identity mismatch")
        if saved.get("aborted"):
            parser.error("P11 anchor candidate was already rejected")
        rows = list(saved.get("rows", []))
    completed = {row["case_id"] for row in rows}
    for case_id, amplitude, values, seed in cases:
        if case_id in completed:
            continue
        original_row = controls[case_id]
        if (original_row["seed_sha256"] != json_digest(seed)
                or original_row["prompt_values"] != list(values)
                or original_row["amplitude"] != amplitude):
            raise RuntimeError("cached original-P11 control identity mismatch")
        candidate = run_arm(seed, "anchor")
        best = max(values)
        best_ids = tuple(index for index, value in enumerate(values, 1) if value == best)
        audit_episode(candidate, seed, "p11", best_ids)
        original = original_row["arms"]["p11"]
        if (candidate["p11_selected_prompt_id"] != original["p11_selected_prompt_id"]
                or candidate["p11_probe_budget"] != original["p11_probe_budget"]
                or candidate["p11_probe_nodes"] != original["p11_probe_nodes"]):
            raise RuntimeError("anchor changed frozen prompt identification")
        anchor = candidate["anchor"]
        total_calibration_budget = candidate["p11_probe_budget"] + anchor["budget"]
        if (total_calibration_budget > 14.0 or anchor["attempts"] > 1
                or anchor["failures"] or anchor["censored"]):
            raise RuntimeError("anchor resource or response evidence failed")
        gain = candidate["score"] - original["score"]
        row = {
            "case_id": case_id, "amplitude": amplitude,
            "topology_block": topology_block(case_id),
            "response_group": response_group(case_id),
            "prompt_values": list(values), "prompt1_best": 1 in best_ids,
            "seed_sha256": json_digest(seed), "paired_gain": gain,
            "control": {"score": original["score"],
                        "action_log_sha256": original["action_log_sha256"],
                        "selected_prompt_id": original["p11_selected_prompt_id"],
                        "probe_nodes": original["p11_probe_nodes"],
                        "probe_budget": original["p11_probe_budget"]},
            "candidate": candidate,
            "anchor_resource": {"probe_budget": candidate["p11_probe_budget"],
                                "anchor_budget": anchor["budget"],
                                "total": total_calibration_budget},
        }
        rows.append(row)
        completed.add(case_id)
        if not math.isfinite(gain) or gain < -10.0:
            raw = {"config": config, "complete": False, "aborted": True,
                   "rejected": True, "rejection_reason": "paired_gain_below_minus_10",
                   "rejection_case": case_id, "rejection_gain": gain, "rows": rows}
            write_json(args.raw_output, raw)
            write_json(args.output, {"config": config, "complete": False,
                       "aborted": True, "development_gate_passed": False,
                       "rejection_reason": raw["rejection_reason"],
                       "rejection_case": case_id, "rejection_gain": gain,
                       "cases_completed": len(rows),
                       "raw_log": {"path": str(args.raw_output),
                                   "sha256": digest(args.raw_output), "committed": False},
                       "production_enabled": False, "confirmation_opened": False})
            print(json.dumps({"aborted": True, "case_id": case_id, "gain": gain}))
            return 0
        write_json(progress, {"config": config, "aborted": False, "rows": rows})
        print(json.dumps({"case_id": case_id, "completed": len(rows),
                          "paired_gain": gain, "total_calibration_budget": total_calibration_budget}),
              flush=True)
    if len(rows) != 252:
        raise RuntimeError("P11 anchor full development cohort incomplete")
    summary = summarize(rows)
    gate = evaluate_gate(summary)
    raw = {"config": config, "complete": True, "aborted": False, "rows": rows}
    write_json(args.raw_output, raw)
    write_json(args.output, {"config": config, "complete": True, "aborted": False,
               "summary": summary, "development_gate": gate,
               "development_gate_passed": gate["passed"],
               "raw_log": {"path": str(args.raw_output),
                           "sha256": digest(args.raw_output), "committed": False},
               "production_enabled": False, "confirmation_opened": False})
    print(json.dumps({"summary": summary, "gate": gate}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

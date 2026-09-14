#!/usr/bin/env python3
"""Screen the 0.9 P11 prior discount against cached original-P11 records."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.analyze_p11_full_policy_validation import (
    analyze as analyze_full_policy,
    audit_episode,
    topology_block,
)
from scripts.run_p11_full_policy_validation import json_digest
from scripts.run_p11_prior_discount import run_arm
from starnet.experiments.p11_validation_seeds import development_cases


PROTOCOL = ROOT / "experiments/manifests/p11-prior-discount-full-development-20260914.json"
DISCOUNT_SOURCE = ROOT / "src/starnet/runtime/p11_prior_discount_experiment.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def response_group(case_id: str) -> str:
    parts = case_id.split(":")
    return "legacy_independent" if parts[0] == "legacy" else parts[3]


def summarize(rows: list[dict]) -> dict:
    gains = [float(row["paired_gain"]) for row in rows]
    topology_means = {
        block: statistics.fmean(
            row["paired_gain"] for row in rows if row["topology_block"] == block
        )
        for block in sorted({row["topology_block"] for row in rows})
    }
    amplitude_means = {
        amplitude: statistics.fmean(
            row["paired_gain"] for row in rows if row["amplitude"] == amplitude
        )
        for amplitude in sorted({row["amplitude"] for row in rows})
    }
    prompt1 = [row["paired_gain"] for row in rows if row["prompt1_best"]]
    return {
        "cases": len(rows),
        "mean": statistics.fmean(gains),
        "minimum": min(gains),
        "maximum": max(gains),
        "win_tie_loss": [
            sum(value > 1e-8 for value in gains),
            sum(abs(value) <= 1e-8 for value in gains),
            sum(value < -1e-8 for value in gains),
        ],
        "prompt1_best_mean": statistics.fmean(prompt1),
        "topology_weighted_mean": statistics.fmean(topology_means.values()),
        "topology_means": topology_means,
        "nonnegative_topology_means": sum(
            value >= -1e-8 for value in topology_means.values()
        ),
        "amplitude_means": amplitude_means,
        "nonnegative_amplitude_means": sum(
            value >= -1e-8 for value in amplitude_means.values()
        ),
    }


def evaluate_gate(summary: dict) -> dict:
    checks = {
        "topology_weighted_mean_gt_1": summary["topology_weighted_mean"] > 1.0,
        "prompt1_best_mean_gt_0": summary["prompt1_best_mean"] > 0.0,
        "at_least_eight_nonnegative_topology_means": (
            summary["nonnegative_topology_means"] >= 8
        ),
        "all_three_amplitude_means_nonnegative": (
            summary["nonnegative_amplitude_means"] == 3
        ),
        "worst_pair_at_least_minus_10": summary["minimum"] >= -10.0,
    }
    return {"checks": checks, "passed": all(checks.values())}


def rejected_pair(gain: float) -> bool:
    return not math.isfinite(gain) or gain < -10.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    control = json.loads(args.control.read_text())
    control_analysis = analyze_full_policy(control, confirmation=False)
    cases = list(development_cases())
    controls = {row["case_id"]: row for row in control["rows"]}
    config = {
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "discount_source_sha256": digest(DISCOUNT_SOURCE),
        "control_path": str(args.control),
        "control_sha256": digest(args.control),
        "control_protocol_sha256": control_analysis["protocol_sha256"],
        "control_source_snapshot": control_analysis["source_snapshot"],
        "cases": len(cases),
        "workers": 1,
        "confirmation_opened": False,
    }
    progress = args.raw_output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("P11 full prior-discount progress identity mismatch")
        if saved.get("aborted"):
            parser.error("P11 full prior-discount candidate was already rejected")
        rows = list(saved.get("rows", []))
    completed = {row["case_id"] for row in rows}
    for case_id, amplitude, values, seed in cases:
        if case_id in completed:
            continue
        control_row = controls[case_id]
        if (control_row["seed_sha256"] != json_digest(seed)
                or control_row["prompt_values"] != list(values)
                or control_row["amplitude"] != amplitude):
            raise RuntimeError("cached original-P11 control identity mismatch")
        candidate = run_arm(seed, discounted=True)
        best = max(values)
        best_ids = tuple(index for index, value in enumerate(values, 1) if value == best)
        audit_episode(candidate, seed, "p11", best_ids)
        original = control_row["arms"]["p11"]
        if (candidate["p11_selected_prompt_id"] != original["p11_selected_prompt_id"]
                or candidate["p11_probe_budget"] != original["p11_probe_budget"]):
            raise RuntimeError("discount changed calibration identity or resource use")
        gain = candidate["score"] - original["score"]
        row = {
            "case_id": case_id,
            "amplitude": amplitude,
            "topology_block": topology_block(case_id),
            "response_group": response_group(case_id),
            "prompt_values": list(values),
            "prompt1_best": 1 in best_ids,
            "seed_sha256": json_digest(seed),
            "paired_gain": gain,
            "control": {
                "score": original["score"],
                "action_log_sha256": original["action_log_sha256"],
                "selected_prompt_id": original["p11_selected_prompt_id"],
                "probe_budget": original["p11_probe_budget"],
            },
            "candidate": candidate,
        }
        rows.append(row)
        completed.add(case_id)
        if rejected_pair(gain):
            raw = {
                "config": config, "complete": False, "aborted": True,
                "rejected": True, "rejection_reason": "paired_gain_below_minus_10",
                "rejection_case": case_id, "rejection_gain": gain, "rows": rows,
            }
            write_json(args.raw_output, raw)
            write_json(args.output, {
                "config": config, "complete": False, "aborted": True,
                "development_gate_passed": False,
                "rejection_reason": raw["rejection_reason"],
                "rejection_case": case_id, "rejection_gain": gain,
                "cases_completed": len(rows),
                "raw_log": {"path": str(args.raw_output),
                            "sha256": digest(args.raw_output), "committed": False},
                "production_enabled": False, "confirmation_opened": False,
            })
            print(json.dumps({"aborted": True, "case_id": case_id, "gain": gain}),
                  flush=True)
            return 0
        write_json(progress, {"config": config, "aborted": False, "rows": rows})
        print(json.dumps({"case_id": case_id, "completed": len(rows),
                          "paired_gain": gain}), flush=True)
    if len(rows) != len(cases):
        raise RuntimeError("P11 full prior-discount cohort incomplete")
    summary = summarize(rows)
    gate = evaluate_gate(summary)
    raw = {"config": config, "complete": True, "aborted": False, "rows": rows}
    write_json(args.raw_output, raw)
    write_json(args.output, {
        "config": config, "complete": True, "aborted": False,
        "summary": summary, "development_gate": gate,
        "development_gate_passed": gate["passed"],
        "raw_log": {"path": str(args.raw_output),
                    "sha256": digest(args.raw_output), "committed": False},
        "production_enabled": False, "confirmation_opened": False,
    })
    print(json.dumps({"summary": summary, "gate": gate}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit the complete frozen bounded-P8 cohort and its preregistered gate."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from starnet.experiments.p9_distribution_seeds import FAMILIES, SHIFT_STRATA
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action

PROTOCOL = ROOT / "experiments/manifests/p9-bounded-release-protocol-20260913.json"
PRIMARY = "bounded_source_vs_p8_submitted"
SECONDARY = "bounded_source_vs_official_best_experimental"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_episode(result):
    """Replay only the recorded public facts; reject invalid action histories."""
    board = Blackboard(node_count=50)
    budget = 100.0
    wasted = 0
    records = result["action_log"]
    if len(records) != result["action_attempts"] or len(records) > 120:
        raise ValueError("inconsistent or excessive action count")
    if (result["action_failures"] or result.get("p8_planning_errors", 0)
            or result.get("model_calls", 0) > 120
            or result.get("llm_forced_failures", 0) > 120):
        raise ValueError("failed action/planner or resource violation")
    for record in records:
        action = Action(record["kind"], record["target_node_1"],
                        target_node_2=record["target_node_2"], prompt_id=record["prompt_id"])
        if not record["success"] or not is_legal_action(action, board, budget):
            raise ValueError("illegal or unsuccessful recorded action")
        if abs(record["budget_before"] - budget) > 1e-8:
            raise ValueError("budget before action mismatch")
        response = record["public_result"]
        if action.kind == "scan":
            success = board.record_scan(action.target_node_1, response)
        elif action.kind == "comm":
            old = board.nodes[action.target_node_1].w
            new = float(response["new_w"])
            if not -100.0 <= new <= 100.0:
                raise ValueError("communication return exceeds measured bounds")
            wasted += int(abs(new - old) <= 1e-8)
            success = board.record_communication(action.target_node_1, response)
        elif action.kind == "cut":
            success = board.record_cut(action.target_node_1, action.target_node_2, response)
        else:
            success = board.record_shield(action.target_node_1, response)
        if not success:
            raise ValueError("public history could not be reconstructed")
        budget -= action_cost(action)
        if abs(record["budget_after"] - budget) > 1e-8:
            raise ValueError("budget after action mismatch")
    if (abs(budget - result["remaining_budget"]) > 1e-8
            or not math.isfinite(result["score"]) or len(board.scanned_ids) != 50):
        raise ValueError("incomplete or inconsistent episode")
    return wasted


def paired_summary(rows, comparison):
    values = [row["paired_deltas"][comparison] for row in rows]
    return {"mean": statistics.fmean(values), "minimum": min(values), "maximum": max(values),
            "win_tie_loss": [sum(x > 1e-8 for x in values), sum(abs(x) <= 1e-8 for x in values), sum(x < -1e-8 for x in values)]}


def block_bootstrap(rows, comparison, repetitions, draws=10000):
    # The seven shifts share a graph and base opinions. They must travel
    # together whenever a graph/repetition is resampled.
    blocks = {(family, repetition): statistics.fmean(
        row["paired_deltas"][comparison] for row in rows
        if row["family"] == family and row["repetition"] == repetition
    ) for family in FAMILIES for repetition in repetitions}
    rng = random.Random(20260913)
    samples = sorted(statistics.fmean(
        blocks[family, rng.choice(repetitions)]
        for family in FAMILIES for _ in repetitions
    ) for _ in range(draws))
    return [samples[int(0.025 * draws)], samples[int(0.975 * draws)]]


def analyze(reports, *, confirmation):
    repetitions = (1001, 1002, 1003) if confirmation else (901, 902)
    expected = set(itertools.product(FAMILIES, repetitions, SHIFT_STRATA))
    rows_by_key = {}
    snapshot = reports[0]["config"]["current_source_snapshot"]
    for report in reports:
        config = report["config"]
        if (config["current_source_snapshot"] != snapshot
                or config["confirmation_opened"] != confirmation):
            raise ValueError("mixed source hashes or cohort")
        for field in ("seed_generator_sha256", "simulation_runner_sha256", "archive_sha256", "mechanism_gate"):
            if config[field] != reports[0]["config"][field]:
                raise ValueError("mixed experiment identities")
        for row in report["rows"]:
            key = row["family"], row["repetition"], row["shift_stratum"]
            if key not in expected or key in rows_by_key:
                raise ValueError("unexpected or repeated paired seed")
            rows_by_key[key] = row
    if set(rows_by_key) != expected:
        raise ValueError(f"incomplete cohort: {len(rows_by_key)}/{len(expected)}")
    rows = [rows_by_key[key] for key in sorted(expected)]
    wasted = dict.fromkeys(("bounded_source", "p8_submitted", "official_best_experimental"), 0)
    for row in rows:
        for arm in wasted:
            result = row["arms"][arm]
            wasted[arm] += audit_episode(result)
            if arm == "bounded_source" and result["source_snapshot"] != snapshot:
                raise ValueError("per-case source identity mismatch")
        for comparison, control in ((PRIMARY, "p8_submitted"), (SECONDARY, "official_best_experimental")):
            difference = row["arms"]["bounded_source"]["score"] - row["arms"][control]["score"]
            if abs(difference - row["paired_deltas"][comparison]) > 1e-8:
                raise ValueError("incorrect paired score")
    primary = paired_summary(rows, PRIMARY)
    ci = block_bootstrap(rows, PRIMARY, repetitions)
    shifts = {shift: paired_summary([row for row in rows if row["shift_stratum"] == shift], PRIMARY)
              for shift in SHIFT_STRATA}
    uncapped_equivalent = all(abs(row["paired_deltas"][PRIMARY]) <= 1e-8
                             for row in rows if row["shift_stratum"] not in ("near_upper_bound", "saturated_hubs"))
    passed = (confirmation and primary["mean"] > 0 and ci[0] > 0
              and all(group["mean"] >= -1e-8 for group in shifts.values()) and uncapped_equivalent)
    return {
        "protocol_sha256": digest(PROTOCOL), "cohort": "confirmation" if confirmation else "development",
        "pairs": len(rows), "primary": {**primary, "block_bootstrap_ci95": ci},
        "by_shift": shifts,
        "by_family": {family: paired_summary([row for row in rows if row["family"] == family], PRIMARY) for family in FAMILIES},
        "secondary_official_best": paired_summary(rows, SECONDARY),
        "secondary_by_shift": {shift: paired_summary([row for row in rows if row["shift_stratum"] == shift], SECONDARY) for shift in SHIFT_STRATA},
        "zero_delta_communication_calls": wasted,
        "uncapped_score_equivalence": uncapped_equivalent,
        "public_history_resource_audit_passed": True,
        "statistical_gate_passed": passed,
        "source_snapshot": snapshot,
        "standard_audit": {"reported_policy_hashes": {"bounded": snapshot["src/starnet/policy/p8_experiment.py"]}},
        "selected_variant": "conservative" if passed else None,
        # This analysis alone does not attest generated ZIP or real LLM checks.
        "variants": {"conservative": {"mean_score_gate_passed": False}},
        "release_gate_pending": "generated ZIP, real LLM route, and target-interpreter checks",
        "platform_score": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--confirmation", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze([json.loads(path.read_text()) for path in args.inputs], confirmation=args.confirmation)
    result["input_sha256"] = {str(path): digest(path) for path in args.inputs}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("pairs", "primary", "zero_delta_communication_calls", "statistical_gate_passed")}), flush=True)


if __name__ == "__main__":
    main()

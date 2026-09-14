#!/usr/bin/env python3
"""Strictly audit P11 full-policy evidence and apply preregistered gates."""

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
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.build_submission import INLINE_MODULES
from starnet.experiments.p11_validation_seeds import confirmation_cases, development_cases
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.cmg import PredictiveState
from starnet.policy.fast_settlement_experiment import FastComponentSettlement


PROTOCOL = ROOT / "experiments/manifests/p11-full-policy-validation-20260914.json"
RUNNER = ROOT / "scripts/run_p11_full_policy_validation.py"
SEED_SOURCE = ROOT / "src/starnet/experiments/p11_validation_seeds.py"
LEDGER = ROOT / "src/starnet/policy/prompt_calibration_experiment.py"
P9_ARCHIVE = ROOT / "artifacts/submission/starnet-p9-bounded-response-20260913.zip"
ARMS = ("p11", "p9_no_probe", "known_best_id_p9_reference",
        "fixed1_online_magnitude_no_probe")
_SETTLEMENT = FastComponentSettlement()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def topology_block(case_id: str) -> str:
    parts = case_id.split(":")
    return ":".join(parts[:2] if parts[0].endswith("_resampled") else parts[:3])


def block_bootstrap(blocks: dict[str, float], draws=10000, seed=20260914):
    names = sorted(blocks)
    rng = random.Random(seed)
    samples = sorted(statistics.fmean(blocks[rng.choice(names)] for _ in names)
                     for _ in range(draws))
    return [samples[int(0.025 * draws)], samples[int(0.975 * draws)]]


def paired_metric(rows, key):
    values = [row["paired"][key] for row in rows]
    return {"cases": len(values), "mean": statistics.fmean(values),
            "minimum": min(values), "maximum": max(values),
            "win_tie_loss": [sum(value > 1e-8 for value in values),
                             sum(abs(value) <= 1e-8 for value in values),
                             sum(value < -1e-8 for value in values)]}


def response_group(case_id: str) -> str:
    parts = case_id.split(":")
    if parts[0] == "legacy":
        return "legacy_independent"
    if parts[0] == "p9":
        return parts[3]
    return parts[2]


def _expected_scans(seed):
    neighbors = {int(node["id"]): [] for node in seed["nodes"]}
    for left, right in seed["edges"]:
        neighbors[int(left)].append(int(right))
        neighbors[int(right)].append(int(left))
    return {int(node["id"]): {"w": float(node["w"]), "persona": str(node["persona"]),
            "comm_left": int(node["comm_left"]), "neighbors": sorted(neighbors[int(node["id"])]),}
            for node in seed["nodes"]}


def audit_episode(result, seed, arm, best_ids):
    records = result["action_log"]
    if (len(records) != result["action_attempts"] or len(records) > 120
            or max(result["host_action_deltas"]) > 1
            or sum(result["host_action_deltas"]) != len(records)
            or result["action_log_sha256"] != json_digest(records)):
        raise ValueError("action/host-step identity mismatch")
    if (result["action_failures"] or result.get("p8_planning_errors", 0)
            or result.get("p11_planning_errors", 0) or result.get("p11_errors", 0)):
        raise ValueError("action or planning failure")
    board = Blackboard(node_count=50)
    budget = 100.0
    scans = _expected_scans(seed)
    hidden = {int(node["id"]): node for node in seed["nodes"]}
    prompts = {int(key): float(value) for key, value in seed["prompts"].items()}
    multipliers = {1: 1.0, 2: 0.5, 3: 0.25}
    for index, record in enumerate(records, 1):
        if record["index"] != index or abs(record["budget_before"] - budget) > 1e-8:
            raise ValueError("nonsequential action or budget")
        action = Action(record["kind"], record["target_node_1"],
                        target_node_2=record["target_node_2"], prompt_id=record["prompt_id"])
        if not record["success"] or not is_legal_action(action, board, budget):
            raise ValueError("illegal recorded action")
        response = record["public_result"]
        if action.kind == "scan":
            if response != scans[action.target_node_1]:
                raise ValueError("scan mismatch")
            success = board.record_scan(action.target_node_1, response)
        elif action.kind == "comm":
            node = board.nodes[action.target_node_1]
            turn = 4 - int(node.comm_left or 0)
            expected = max(-100.0, min(100.0, node.w + prompts[action.prompt_id]
                           * float(hidden[action.target_node_1]["r"]) * multipliers[turn]))
            if response.get("status") != "success" or abs(float(response["new_w"]) - expected) > 1e-8:
                raise ValueError("communication response mismatch")
            if arm == "known_best_id_p9_reference":
                if (record.get("requested_prompt_id") != 1
                        or record.get("dispatched_prompt_id") not in best_ids):
                    raise ValueError("known-ID mapping mismatch")
            elif action.prompt_id != 1 and arm != "p11":
                raise ValueError("non-P11 arm changed prompt ID")
            success = board.record_communication(action.target_node_1, response)
        elif action.kind == "cut":
            success = board.record_cut(action.target_node_1, action.target_node_2, response)
        else:
            success = board.record_shield(action.target_node_1, response)
        if not success:
            raise ValueError("public action replay failed")
        budget -= action_cost(action)
        if abs(record["budget_after"] - budget) > 1e-8:
            raise ValueError("post-action budget mismatch")
    score = _SETTLEMENT.score(PredictiveState.from_blackboard(board))
    if (abs(result["remaining_budget"] - budget) > 1e-8
            or abs(result["score"] - score) > 1e-8 or not math.isfinite(score)):
        raise ValueError("terminal state mismatch")


def source_snapshot_paths():
    names = set(INLINE_MODULES) | {
        "src/starnet/policy/prompt_calibration_experiment.py",
        "src/starnet/runtime/p11_prompt_controller_experiment.py",
        "src/starnet/submission/config.json",
    }
    names.update(str(path.relative_to(ROOT))
                 for path in (ROOT / "src/starnet/submission/prompt").glob("*.txt"))
    return names


def analyze(raw, *, confirmation):
    config = raw["config"]
    if (raw.get("complete") is not True or config.get("cohort") !=
            ("confirmation" if confirmation else "development")):
        raise ValueError("wrong or incomplete cohort")
    expected_rows = list(confirmation_cases(allow_confirmation=True) if confirmation
                         else development_cases())
    expected = {case_id: (amplitude, values, seed)
                for case_id, amplitude, values, seed in expected_rows}
    rows = {row["case_id"]: row for row in raw["rows"]}
    if len(rows) != len(raw["rows"]) or set(rows) != set(expected):
        raise ValueError("cohort Cartesian identity mismatch")
    if (config.get("protocol_sha256") != digest(PROTOCOL)
            or config.get("runner_sha256") != digest(RUNNER)
            or config.get("seed_source_sha256") != digest(SEED_SOURCE)
            or config.get("ledger_sha256") != digest(LEDGER)
            or config.get("p9_archive_sha256") != digest(P9_ARCHIVE)):
        raise ValueError("source identity mismatch")
    snapshot = config.get("source_snapshot", {})
    if set(snapshot) != source_snapshot_paths() or any(
        digest(ROOT / path) != value for path, value in snapshot.items()
    ):
        raise ValueError("runtime snapshot mismatch")

    ordered = []
    for case_id, (amplitude, values, seed) in expected.items():
        row = rows[case_id]
        best = max(values)
        best_ids = tuple(index for index, value in enumerate(values, 1) if value == best)
        if (row["amplitude"] != amplitude or row["prompt_values"] != list(values)
                or row["best_prompt_ids"] != list(best_ids)
                or row["seed_sha256"] != json_digest(seed)
                or row["topology_block"] != topology_block(case_id)
                or set(row["arms"]) != set(ARMS)):
            raise ValueError("case metadata mismatch")
        for arm in ARMS:
            audit_episode(row["arms"][arm], seed, arm, best_ids)
        scores = {arm: row["arms"][arm]["score"] for arm in ARMS}
        expected_pairs = {"p11_vs_p9": scores["p11"] - scores["p9_no_probe"],
            "p11_signed_gap_to_known_id": scores["known_best_id_p9_reference"] - scores["p11"],
            "p9_signed_gap_to_known_id": scores["known_best_id_p9_reference"] - scores["p9_no_probe"],
            "magnitude_vs_p9": scores["fixed1_online_magnitude_no_probe"] - scores["p9_no_probe"]}
        if any(abs(row["paired"][key] - value) > 1e-8 for key, value in expected_pairs.items()):
            raise ValueError("paired score mismatch")
        ordered.append(row)

    def mean(rows_, key="p11_vs_p9"):
        return statistics.fmean(row["paired"][key] for row in rows_)
    core = ([row for row in ordered if row["amplitude"].startswith("core_")]
            if confirmation else ordered)
    block_values = {block: mean([row for row in core if row["topology_block"] == block])
                    for block in sorted({row["topology_block"] for row in core})}
    expected_block_count = 12 if confirmation else 10
    if len(block_values) != expected_block_count:
        raise ValueError("topology block count mismatch")
    primary_mean = statistics.fmean(block_values.values())
    ci = block_bootstrap(block_values)
    unique = [row for row in core if len(row["best_prompt_ids"]) == 1]
    prompt1_best = [row for row in unique if row["prompt1_best"]]
    prompt1_wrong = [row for row in unique if not row["prompt1_best"]]
    exploration_cost = statistics.fmean(-row["paired"]["p11_vs_p9"] for row in prompt1_best)
    wrong_p9_gap = mean(prompt1_wrong, "p9_signed_gap_to_known_id")
    p9_gap = mean(unique, "p9_signed_gap_to_known_id")
    p11_gap = mean(unique, "p11_signed_gap_to_known_id")
    exploration_allowed = max(5.0, 0.25 * wrong_p9_gap)
    identification = all(row["identified_best"] for row in unique
                         if not row["arms"]["p11"]["ledger"]["censored"])
    resource_pass = all(
        row["arms"][arm]["action_failures"] == 0
        and row["arms"][arm].get("p11_planning_errors", 0) == 0
        and row["arms"][arm].get("p11_errors", 0) == 0
        for row in ordered for arm in ARMS
    )
    calibration_pass = all(
        row["arms"]["p11"]["p11_probe_failures"] == 0
        and (0.0 <= row["arms"]["p11"]["p11_probe_budget"] <= 12.0)
        and row["arms"]["p11"]["p11_probe_budget"] % 2.0 == 0.0
        and (confirmation or row["arms"]["p11"]["p11_probe_budget"] in (6.0, 12.0))
        and (confirmation or not row["arms"]["p11"]["ledger"]["censored"])
        and not row["arms"]["p11"]["ledger"]["failures"]
        for row in ordered
    )
    base_prompt1 = [row for row in ordered
                    if row["amplitude"] in {"base", "core_medium"} and row["prompt1_best"]]
    result = {"cohort": "confirmation" if confirmation else "development",
        "cases": len(ordered), "topology_blocks": block_values,
        "primary": {"block_weighted_mean": primary_mean, "block_bootstrap_ci95": ci},
        "identification_passed": identification, "resource_audit_passed": resource_pass,
        "calibration_audit_passed": calibration_pass,
        "exploration": {"prompt1_best_mean_cost": exploration_cost,
                        "allowed_cost": exploration_allowed,
                        "gate_passed": exploration_cost <= exploration_allowed},
        "known_id_signed_gap": {"p9_mean": p9_gap, "p11_mean": p11_gap,
            "gate_passed": p9_gap > 0.0 and p11_gap <= 0.4 * p9_gap},
        "base_prompt1_best_mean_gain": mean(base_prompt1) if base_prompt1 else None,
        "by_amplitude": {amplitude: paired_metric(
            [row for row in ordered if row["amplitude"] == amplitude], "p11_vs_p9")
            for amplitude in sorted({row["amplitude"] for row in ordered})},
        "by_response_group": {group: paired_metric(
            [row for row in ordered if response_group(row["case_id"]) == group], "p11_vs_p9")
            for group in sorted({response_group(row["case_id"]) for row in ordered})},
        "by_best_prompt_id": {str(prompt_id): paired_metric(
            [row for row in unique if row["best_prompt_ids"] == [prompt_id]], "p11_vs_p9")
            for prompt_id in (1, 2, 3)},
        "decomposition": {
            "fixed1_online_magnitude_vs_p9": paired_metric(ordered, "magnitude_vs_p9"),
            "prompt_learning_beyond_magnitude": {
                "cases": len(ordered),
                "mean": statistics.fmean(
                    row["arms"]["p11"]["score"]
                    - row["arms"]["fixed1_online_magnitude_no_probe"]["score"]
                    for row in ordered
                ),
            },
        },
        "probe": {
            "mean_budget": statistics.fmean(
                row["arms"]["p11"]["p11_probe_budget"] for row in ordered
            ),
            "budget_6_cases": sum(row["arms"]["p11"]["p11_probe_budget"] == 6.0
                                  for row in ordered),
            "budget_12_cases": sum(row["arms"]["p11"]["p11_probe_budget"] == 12.0
                                   for row in ordered),
            "fallback_cases": sum(row["arms"]["p11"]["p11_fallback_to_p9"]
                                  for row in ordered),
            "confident_cases": sum(row["arms"]["p11"]["ledger"]["confident"]
                                   for row in ordered),
        },
        "losses_vs_p9": sorted(
            ({"case_id": row["case_id"], "delta": row["paired"]["p11_vs_p9"],
              "probe_budget": row["arms"]["p11"]["p11_probe_budget"],
              "selected_prompt_id": row["arms"]["p11"]["p11_selected_prompt_id"]}
             for row in ordered if row["paired"]["p11_vs_p9"] < -1e-8),
            key=lambda item: item["delta"],
        )}
    common = (resource_pass and calibration_pass and identification
              and primary_mean > 0 and ci[0] > 0
              and result["exploration"]["gate_passed"]
              and result["known_id_signed_gap"]["gate_passed"])
    if confirmation:
        full = [row for row in ordered if not row["amplitude"].startswith("stress_")]
        stress = [row for row in ordered if row["amplitude"] == "stress_degree"]
        family_means = {family: mean([row for row in core if row["case_id"].startswith(family + ":")])
                        for family in ("er_resampled", "ba_resampled", "ws_resampled", "sbm_resampled")}
        result["confirmation"] = {"core_cases": len(core), "core_mean": mean(core),
            "core_plus_edge_cases": len(full), "core_plus_edge_mean": mean(full),
            "degree_stress_cases": len(stress), "degree_stress_mean": mean(stress),
            "family_means": family_means}
        common = (common and mean(full) > 0 and mean(stress) >= -1e-8
                  and sum(value > 1e-8 for value in family_means.values()) >= 2)
    result["gate_passed"] = common
    result["protocol_sha256"] = config["protocol_sha256"]
    result["source_snapshot"] = config["source_snapshot"]
    result["selected_variant"] = "prompt_learning"
    if confirmation:
        result["statistical_gate_passed"] = common
    else:
        result["development_gate_passed"] = common
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirmation", action="store_true")
    args = parser.parse_args()
    raw = json.loads(args.input.read_text())
    result = analyze(raw, confirmation=args.confirmation)
    result["input_sha256"] = digest(args.input)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

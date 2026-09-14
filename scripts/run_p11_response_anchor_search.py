#!/usr/bin/env python3
"""Compare frozen P11 with one post-calibration selected-prompt anchor."""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_submission_archives import CountingLLM
from scripts.run_p11_full_policy_validation import run_model
from scripts.run_p9_distribution_validation import LoggedEnvironment
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.runtime.p11_prompt_controller_experiment import PromptLearningRuntimeController
from starnet.runtime.p11_response_anchor_experiment import AnchoredPromptLearningController
from starnet.runtime.stage import ContestStage
from starnet.submission.starnet_model import ParticipantSquadModel


PROTOCOL = ROOT / "experiments/manifests/p11-selected-prompt-anchor-development-20260914.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def source_snapshot():
    paths = (
        "src/starnet/policy/prompt_calibration_experiment.py",
        "src/starnet/runtime/p11_prompt_controller_experiment.py",
        "src/starnet/runtime/p11_response_anchor_experiment.py",
    )
    return {path: digest(ROOT / path) for path in paths}


def run_arm(seed, arm):
    env = LoggedEnvironment(seed)
    llm = CountingLLM(1.0, offline_only=True)
    people = json.loads((ROOT / "src/starnet/submission/config.json").read_text())["person"]
    model = ParticipantSquadModel(env, people, llm)
    controller_type = (
        PromptLearningRuntimeController if arm == "low"
        else AnchoredPromptLearningController
    )
    model.controller = controller_type(
        env, llm_ranker=lambda payload: None,
        stage=ContestStage.PRELIMINARY, config=model.controller.config,
        p8_mode="conservative", max_probe_budget=6.0, max_probe_nodes=1,
        require_stage_envelope=True,
    )
    controller = model.controller
    result = run_model(model, env)
    result["arm"] = arm
    if arm == "anchor":
        result["anchor"] = {
            "target": controller.p11_anchor_target,
            "attempts": controller.p11_anchor_attempts,
            "successes": controller.p11_anchor_successes,
            "failures": controller.p11_anchor_failures,
            "censored": controller.p11_anchor_censored,
            "budget": controller.p11_anchor_budget,
            "used": controller.p11_anchor_used,
            "skip_reason": controller.p11_anchor_skip_reason,
            "population_prior": controller.p11_anchor_population_prior,
            "selected_observations": dict(controller.p11_selected_prompt_observations),
        }
    return result


def erased_persuasion(result):
    actions = [item for item in result["action_log"] if item["kind"] != "scan"]
    shield = {item["target_node_1"]: index for index, item in enumerate(actions)
              if item["kind"] == "shield"}
    erased = [item for index, item in enumerate(actions)
              if item["kind"] == "comm" and item["target_node_1"] in shield
              and index < shield[item["target_node_1"]]]
    return {"count": len(erased), "budget": 2.0 * len(erased),
            "nodes": sorted({item["target_node_1"] for item in erased})}


def first_divergence(anchor, low):
    left, right = anchor["action_log"], low["action_log"]
    for index in range(max(len(left), len(right))):
        first = left[index] if index < len(left) else None
        second = right[index] if index < len(right) else None
        keys = ("kind", "target_node_1", "target_node_2", "prompt_id")
        if ((tuple(first.get(key) for key in keys) if first else None)
                != (tuple(second.get(key) for key in keys) if second else None)):
            return {"action_index": index + 1, "anchor": first, "low": second}
    return None


def metric(values):
    return {"cases": len(values), "mean": statistics.fmean(values),
            "minimum": min(values), "maximum": max(values),
            "win_tie_loss": [sum(value > 1e-8 for value in values),
                             sum(abs(value) <= 1e-8 for value in values),
                             sum(value < -1e-8 for value in values)]}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = source_snapshot()
    config = {"protocol_sha256": digest(PROTOCOL), "runner_sha256": digest(Path(__file__)),
              "source_snapshot": snapshot, "families": list(SEED_SPECS),
              "prompt_configs": 6, "cases": 36, "workers": 1,
              "confirmation_opened": False}
    progress = args.raw_output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("anchor progress identity mismatch")
        rows = list(saved["rows"])
    completed = {row["case_id"] for row in rows}
    for family in SEED_SPECS:
        original = seed_payload(family, 50, 1)
        for values in itertools.permutations((15.0, 10.0, -5.0)):
            name = "_".join(str(int(value)) for value in values)
            case_id = f"{family}:{name}"
            if case_id in completed:
                continue
            if source_snapshot() != snapshot:
                raise RuntimeError("anchor source changed during experiment")
            seed = copy.deepcopy(original)
            seed["prompts"] = {str(index): value for index, value in enumerate(values, 1)}
            low = run_arm(seed, "low")
            anchor = run_arm(seed, "anchor")
            best = max(values)
            best_ids = [index for index, value in enumerate(values, 1) if value == best]
            row = {"case_id": case_id, "family": family,
                   "prompt_values": list(values), "best_prompt_ids": best_ids,
                   "prompt1_best": 1 in best_ids, "seed_sha256": json_digest(seed),
                   "arms": {"low": low, "anchor": anchor},
                   "paired": {"anchor_vs_low": anchor["score"] - low["score"]},
                   "identified": {"low": low["p11_selected_prompt_id"] in best_ids,
                                  "anchor": anchor["p11_selected_prompt_id"] in best_ids},
                   "probe_nodes": low["p11_probe_nodes"],
                   "anchor": anchor["anchor"],
                   "initial_low_prompt_prior": low["ledger"]["normalized_values"],
                   "final_selected_observations": {
                       "low": low["p11_selected_prompt_observations"],
                       "anchor": anchor["p11_selected_prompt_observations"]},
                   "erased_persuasion": {"low": erased_persuasion(low),
                                          "anchor": erased_persuasion(anchor)},
                   "first_divergence": first_divergence(anchor, low)}
            failures = sum(arm.get(key, 0) for arm in (low, anchor)
                           for key in ("action_failures", "p8_planning_errors",
                                       "p11_planning_errors", "p11_errors"))
            if (low["p11_probe_budget"] != 6.0 or anchor["p11_probe_budget"] != 6.0
                    or anchor["anchor"]["budget"] != 2.0
                    or not all(row["identified"].values()) or failures):
                raise RuntimeError("anchor case violated identity, cost, or runtime contract")
            rows.append(row)
            completed.add(case_id)
            write_json(progress, {"config": config, "rows": rows})
            print(json.dumps({"case_id": case_id, "completed": len(rows),
                              "anchor_vs_low": row["paired"]["anchor_vs_low"],
                              "probe_node": row["probe_nodes"],
                              "anchor_target": row["anchor"]["target"]}), flush=True)
    deltas = [row["paired"]["anchor_vs_low"] for row in rows]
    prompt1 = [row["paired"]["anchor_vs_low"] for row in rows if row["prompt1_best"]]
    family = {name: statistics.fmean(row["paired"]["anchor_vs_low"] for row in rows
                                     if row["family"] == name) for name in SEED_SPECS}
    gate = {"symmetric_mean_gt_1": statistics.fmean(deltas) > 1.0,
            "prompt1_best_mean_gt_0": statistics.fmean(prompt1) > 0.0,
            "nonnegative_family_means_at_least_4": sum(value >= -1e-8 for value in family.values()) >= 4,
            "minimum_pair_at_least_minus_10": min(deltas) >= -10.0,
            "identity_cost_and_runtime_passed": True}
    raw = {"config": config, "complete": len(rows) == 36, "rows": rows}
    write_json(args.raw_output, raw)
    compact = {"config": config, "complete": raw["complete"],
               "summary": {"anchor_vs_low": metric(deltas),
                           "prompt1_best_anchor_vs_low": metric(prompt1),
                           "family_mean_anchor_vs_low": family,
                           "erased_persuasion": {arm: {
                               "count": sum(row["erased_persuasion"][arm]["count"] for row in rows),
                               "budget": sum(row["erased_persuasion"][arm]["budget"] for row in rows)}
                               for arm in ("low", "anchor")}},
               "gate": gate, "development_gate_passed": all(gate.values()),
               "raw_log": {"path": str(args.raw_output), "sha256": digest(args.raw_output),
                           "committed": False},
               "rows": [{key: row[key] for key in (
                   "case_id", "family", "prompt_values", "best_prompt_ids", "prompt1_best",
                   "seed_sha256", "paired", "identified", "probe_nodes", "anchor",
                   "initial_low_prompt_prior", "final_selected_observations",
                   "erased_persuasion", "first_divergence")}
                   for row in rows], "production_enabled": False,
               "confirmation_opened": False}
    write_json(args.output, compact)
    print(json.dumps({"gate": gate, "summary": compact["summary"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

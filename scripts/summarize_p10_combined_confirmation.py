#!/usr/bin/env python3
"""Create the compact P10 confirmation report from immutable full raw evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_p10_combined_confirmation import digest, summarize
from starnet.experiments.p10_confirmation_seeds import FAMILIES, STRATA


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    input_path = args.input.resolve()
    raw = json.loads(input_path.read_text())
    rows = raw["rows"]
    if raw.get("complete") is not True or len(rows) != 48:
        raise RuntimeError("raw confirmation evidence is incomplete")
    blocks = {
        (family, repetition): statistics.fmean(
            row["paired_deltas"]["candidate_vs_p9"] for row in rows
            if row["family"] == family and row["repetition"] == repetition
        )
        for family in FAMILIES for repetition in (1201, 1202, 1203)
    }
    rng = random.Random(20260914)
    bootstrap = sorted(statistics.fmean(
        blocks[family, rng.choice((1201, 1202, 1203))]
        for family in FAMILIES for _ in (1201, 1202, 1203)
    ) for _ in range(10000))
    summary = summarize(rows)
    candidate_results = [row["arms"]["candidate"] for row in rows]
    audit = {
        "action_failures": sum(result["action_failures"] for result in candidate_results),
        "p8_planning_errors": sum(result["p8_planning_errors"] for result in candidate_results),
        "p10_planning_errors": sum(result["p10_planning_errors"] for result in candidate_results),
        "bad_host_step_cases": sum(
            not result["one_action_per_host_step"]
            or sum(result["host_action_deltas"]) != result["action_attempts"]
            for result in candidate_results
        ),
        "approved_plans": sum(result["p10_approved_plans"] for result in candidate_results),
        "completed_plans": sum(result["p10_prefix_completed"] for result in candidate_results),
        "prefix_failures": sum(result["p10_prefix_failures"] for result in candidate_results),
        "pending_prefix_actions": sum(result["p10_pending_count"] for result in candidate_results),
        "response_disabled_cases": sum(result["p10_response_disabled"] for result in candidate_results),
        "response_activations_by_stratum": {
            stratum: sum(
                row["arms"]["candidate"]["p10_response_activation"] is not None
                for row in rows if row["stratum"] == stratum
            ) for stratum in STRATA
        },
    }
    stratum_means = {
        stratum: summary["by_stratum"][stratum]["candidate_vs_p9"]["mean"]
        for stratum in STRATA
    }
    family_means = {
        family: summary["by_family"][family]["candidate_vs_p9"]["mean"]
        for family in FAMILIES
    }
    gate = {
        "bootstrap_ci95": [bootstrap[250], bootstrap[9750]],
        "overall_mean_positive": summary["overall"]["candidate_vs_p9"]["mean"] > 0.0,
        "bootstrap_lower_positive": bootstrap[250] > 0.0,
        "each_stratum_mean_nonnegative": min(stratum_means.values()) >= -1e-8,
        "positive_topology_family_means": sum(value > 1e-8 for value in family_means.values()),
        "protocol_resources_passed": all(value == 0 for value in (
            audit["action_failures"], audit["p8_planning_errors"],
            audit["p10_planning_errors"], audit["bad_host_step_cases"],
            audit["prefix_failures"], audit["pending_prefix_actions"],
            audit["response_disabled_cases"],
        )),
    }
    gate["statistical_release_gate_passed"] = (
        gate["overall_mean_positive"] and gate["bootstrap_lower_positive"]
        and gate["each_stratum_mean_nonnegative"]
        and gate["positive_topology_family_means"] >= 2
        and gate["protocol_resources_passed"]
    )
    compact = {
        "config": raw["config"], "complete": True, "summary": summary,
        "audit": audit, "release_gate": gate,
        "raw_log": {"path": str(input_path.relative_to(ROOT)),
                    "sha256": digest(input_path), "committed": False},
        "rows": [{"family": row["family"], "repetition": row["repetition"],
                  "stratum": row["stratum"], "seed_sha256": row["seed_sha256"],
                  "paired_deltas": row["paired_deltas"],
                  "first_divergence": row["first_divergence"],
                  "arms": {arm: {key: result.get(key) for key in (
                      "score", "remaining_budget", "host_calls", "action_attempts",
                      "action_failures", "action_log_sha256", "max_actions_per_host_step",
                      "one_action_per_host_step", "controller_type", "effective_p8_mode",
                      "effective_policy_mode", "llm_calls", "llm_accepted", "llm_fallbacks",
                      "p8_planning_errors", "p10_planning_errors", "p10_experiment_mode",
                      "p10_searches", "p10_search_completed", "p10_plan_id",
                      "p10_plan_decision", "p10_approved_plans", "p10_baseline_choices",
                      "p10_prefix_successes", "p10_prefix_completed", "p10_prefix_failures",
                      "p10_pending_count", "p10_response_switches", "p10_response_disabled",
                      "p10_response_disable_reason", "p10_response_activation",
                      "p10_response_final_weights")}
                           for arm, result in row["arms"].items()}}
                 for row in rows],
        "production_enabled": False, "platform_score": None,
    }
    write_json(args.output, compact)
    print(json.dumps({"complete": True, "summary": compact["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Paired public-response allocation ablation on the local public API model.

The strategy receives scans and communicate responses only.  ``r`` remains
inside ``LocalPublicEnvironment``; this script never reads it after the seed
has constructed the environment.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from run_local_policy_matrix import (
    INDEPENDENT_FAMILIES,
    LocalPublicEnvironment,
    independent_seed_payload,
)
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.response_experiment import PriorMode, ResponseBudgetPlanner
from starnet.runtime.env_adapter import apply_action_outcome


MODES: tuple[PriorMode, ...] = ("fixed", "pooled", "persona_shrunk")


def run_variant(seed: Mapping[str, Any], mode: PriorMode) -> dict[str, Any]:
    """Run scan-all then one public-only replan after every response."""
    env = LocalPublicEnvironment(seed)
    board = Blackboard(node_count=len(seed["nodes"]))
    board.set_budget(env.get_remaining_budget())
    planner = ResponseBudgetPlanner(prior_mode=mode)
    scans = comms = failures = 0
    for node_id in range(1, len(seed["nodes"]) + 1):
        outcome = apply_action_outcome(env, board, Action("scan", node_id), env.get_remaining_budget())
        scans += 1
        if not outcome.succeeded:
            failures += 1
    while True:
        choice = planner.next_choice(board, env.get_remaining_budget())
        if choice is None:
            break
        node = board.nodes[choice.action.target_node_1]
        before_w, persona = node.w, node.persona
        outcome = apply_action_outcome(env, board, choice.action, env.get_remaining_budget())
        comms += 1
        if not outcome.succeeded:
            failures += 1
            break
        raw = outcome.raw_response
        if choice.turn == 1 and isinstance(raw, Mapping) and isinstance(raw.get("new_w"), (int, float)):
            planner.observe_success(choice.action.target_node_1, persona, before_w, float(raw["new_w"]), choice.turn)
    return {
        "score": env.evaluate(), "scans": scans, "communications": comms,
        "failures": failures, "remaining_budget": env.get_remaining_budget(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=("existing", "independent"), default="independent")
    parser.add_argument("--node-count", type=int, default=50)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.node_count <= 0 or args.repetitions <= 0:
        raise SystemExit("node-count and repetitions must be positive")
    families = SEED_SPECS if args.block == "existing" else INDEPENDENT_FAMILIES
    make_seed = seed_payload if args.block == "existing" else independent_seed_payload
    rows: list[dict[str, Any]] = []
    for family in families:
        for repetition in range(1, args.repetitions + 1):
            seed = make_seed(family, args.node_count, repetition)
            for mode in MODES:
                rows.append({
                    "family": family, "repetition": repetition, "mode": mode,
                    **run_variant(seed, mode),
                })
    fixed = {(row["family"], row["repetition"]): row for row in rows if row["mode"] == "fixed"}
    comparisons: dict[str, dict[str, Any]] = {}
    for mode in MODES[1:]:
        selected = [row for row in rows if row["mode"] == mode]
        deltas = [row["score"] - fixed[(row["family"], row["repetition"])]["score"] for row in selected]
        by_family = {
            family: sum(
                row["score"] - fixed[(row["family"], row["repetition"])]["score"]
                for row in selected if row["family"] == family
            ) / args.repetitions
            for family in families
        }
        comparisons[mode] = {
            "mean_delta_vs_fixed": sum(deltas) / len(deltas),
            "minimum_paired_delta": min(deltas),
            "family_mean_deltas": by_family,
            "all_family_means_positive": all(value > 0.0 for value in by_family.values()),
            "zero_failures": all(row["failures"] == 0 for row in selected),
        }
    payload = {
        "scope": "scan-all, communication-only public-response ablation",
        "block": args.block, "node_count": args.node_count, "repetitions": args.repetitions,
        "families": list(families), "rows": rows, "comparisons": comparisons,
        "promotion_rule": "promote only if both calibrated modes have positive mean delta in every family and zero failures",
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

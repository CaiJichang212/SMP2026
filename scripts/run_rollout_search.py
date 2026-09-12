#!/usr/bin/env python3
"""Paired local P7 rollout screen; scores are not official results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import (
    HOLDOUT_FAMILIES, INDEPENDENT_FAMILIES, LocalPublicEnvironment,
    holdout_seed_payload, independent_seed_payload, run_variant,
)
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.rollout_experiment import choose_rollout_action
from starnet.runtime.env_adapter import apply_action_outcome


FAMILIES = (
    *((name, seed_payload) for name in SEED_SPECS),
    *((name, independent_seed_payload) for name in INDEPENDENT_FAMILIES),
    *((name, holdout_seed_payload) for name in HOLDOUT_FAMILIES),
)


def run_search(seed, *, scenario_count: int = 1, env_factory=LocalPublicEnvironment):
    started = time.perf_counter()
    env = env_factory(seed)
    count = len(seed["nodes"])
    board = Blackboard(node_count=count)
    actions = dict.fromkeys(("scan", "comm", "cut", "shield"), 0)
    first_responses: dict[int, float] = {}
    failures = planning_calls = rollouts = steps = 0
    limit = 117 if count <= 50 else 247
    for node_id in range(1, count + 1):
        action = Action("scan", node_id)
        budget = env.get_remaining_budget()
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal scan")
        if not apply_action_outcome(env, board, action, budget).succeeded:
            raise RuntimeError("scan failed")
        actions["scan"] += 1
        steps += 1
    while steps < limit:
        budget = env.get_remaining_budget()
        decision = choose_rollout_action(
            board, budget, first_responses,
            remaining_steps=limit - steps, scenario_count=scenario_count,
        )
        planning_calls += 1
        rollouts += decision.rollouts
        action = decision.action
        if action is None:
            break
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal planned action")
        old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        actions[action.kind] += 1
        steps += 1
        if not outcome.succeeded:
            failures += 1
            break
        if action.kind == "comm" and turn == 1:
            first_responses[action.target_node_1] = board.nodes[action.target_node_1].w - old_w
    return {
        "score": env.evaluate(), "actions": actions, "failures": failures,
        "remaining_budget": env.get_remaining_budget(), "steps": steps,
        "planning_calls": planning_calls, "rollouts": rollouts,
        "seconds": time.perf_counter() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=301)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--nodes", type=int, choices=(50, 100), default=50)
    parser.add_argument("--scenarios", type=int, choices=(1, 3), default=1)
    parser.add_argument("--family", choices=tuple(name for name, _ in FAMILIES))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.start < 1 or args.repetitions < 1:
        parser.error("start and repetitions must be positive")
    chosen = [(name, generator) for name, generator in FAMILIES if args.family in (None, name)]
    rows = []
    for name, generator in chosen:
        for repetition in range(args.start, args.start + args.repetitions):
            seed = generator(name, args.nodes, repetition)
            baseline = run_variant(seed, "public_greedy")
            candidate = run_search(seed, scenario_count=args.scenarios)
            row = {"family": name, "repetition": repetition,
                   "variant": "mean" if args.scenarios == 1 else "sampled",
                   "baseline": baseline,
                   "candidate": candidate, "delta": candidate["score"] - baseline["score"]}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    means = {name: statistics.mean(row["delta"] for row in rows if row["family"] == name)
             for name, _ in chosen}
    report = {
        "config": {**vars(args), "output": str(args.output), "block": "old_13_families"},
        "rows": rows,
        "family_mean_delta": means,
        "mean_delta": statistics.mean(row["delta"] for row in rows),
        "all_family_means_nonnegative": all(value >= -1e-8 for value in means.values()),
        "platform_score": None, "promotion_allowed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

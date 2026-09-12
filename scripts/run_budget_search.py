#!/usr/bin/env python3
"""Paired offline budget-search screen; scores are not platform results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time

try:
    from scripts.run_local_policy_matrix import (
        HOLDOUT_FAMILIES, INDEPENDENT_FAMILIES, LocalPublicEnvironment,
        holdout_seed_payload, independent_seed_payload, run_variant,
    )
except ModuleNotFoundError:
    from run_local_policy_matrix import (
        HOLDOUT_FAMILIES, INDEPENDENT_FAMILIES, LocalPublicEnvironment,
        holdout_seed_payload, independent_seed_payload, run_variant,
    )
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.baseline import _response, public_response
from starnet.policy.budget_experiment import budget_plan
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.structural import ExperimentalPublicGreedyPlanner, public_positive_graph_gate_closed
from starnet.runtime.env_adapter import apply_action_outcome


def run_search(seed, *, depth=2, width=4, observation_slots=0, gate="off"):
    if gate not in {"off", "negative_mass", "baseline"}:
        raise ValueError("unknown budget search gate")
    started = time.perf_counter()
    env = LocalPublicEnvironment(seed)
    count = len(seed["nodes"])
    board = Blackboard(node_count=count)
    actions = dict.fromkeys(("scan", "comm", "cut", "shield"), 0)
    failures = steps = 0
    first_responses = {}
    limit = 117 if count <= 50 else 247
    for node_id in range(1, count + 1):
        action = Action("scan", node_id)
        if not is_legal_action(action, board, env.get_remaining_budget()):
            raise RuntimeError("illegal scan")
        outcome = apply_action_outcome(env, board, action, env.get_remaining_budget())
        actions["scan"] += 1
        steps += 1
        if not outcome.succeeded:
            raise RuntimeError("scan failed")
    degree = dict.fromkeys(board.nodes, 0)
    for left, right in board.edges:
        degree[left] += 1
        degree[right] += 1
    weighted_total = sum((degree[node_id] + 1) * node.w for node_id, node in board.nodes.items())
    enabled = gate == "off" or (gate == "negative_mass" and weighted_total < 0)
    while steps < limit:
        budget = env.get_remaining_budget()
        estimate = _response if public_positive_graph_gate_closed(board) else public_response
        response_fn = lambda node_id, node, turn: estimate(
            node_id, node.persona, turn, first_responses, DEFAULT_CALIBRATION_PROFILE,
        )
        if enabled:
            plan = budget_plan(board, budget, response_fn, remaining_steps=limit - steps, depth=depth, width=width)
            if not plan.actions:
                break
            action = plan.actions[0]
            if len(first_responses) < observation_slots:
                # Observe a response on a retained target before irreversible
                # structure. Only the first action executes; feedback replans all.
                action = next((item for item in plan.actions if item.kind == "comm"
                               and item.target_node_1 not in first_responses), action)
        else:
            planner = ExperimentalPublicGreedyPlanner(response_fn, candidate_limit=24,
                                                      min_observed_responses=0, structure_roi_margin=1.0)
            candidates = planner.candidates(board, budget, observed_response_count=len(first_responses))
            if not candidates:
                break
            action = candidates[0].action
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal planned action")
        old_w = board.nodes[action.target_node_1].w
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        actions[action.kind] += 1
        steps += 1
        if not outcome.succeeded:
            failures += 1
            break
        if action.kind == "comm":
            first_responses.setdefault(action.target_node_1, (board.nodes[action.target_node_1].w - old_w) / (0.5 ** (turn - 1)))
    return {"score": env.evaluate(), "actions": actions, "failures": failures,
            "remaining_budget": env.get_remaining_budget(), "steps": steps,
            "seconds": time.perf_counter() - started, "search_enabled": enabled}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=("existing", "independent", "holdout"), default="existing")
    parser.add_argument("--start", type=int, default=31)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--nodes", type=int, choices=(50, 100), default=50)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--width", type=int, default=4)
    parser.add_argument("--observation-slots", type=int, default=0)
    parser.add_argument("--gate", choices=("off", "negative_mass", "baseline"), default="off")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.start < 1 or args.repetitions < 1 or args.depth < 0 or args.width < 1 or args.observation_slots < 0:
        parser.error("invalid experiment limits")
    families, generator = {"existing": (SEED_SPECS, seed_payload),
                           "independent": (INDEPENDENT_FAMILIES, independent_seed_payload),
                           "holdout": (HOLDOUT_FAMILIES, holdout_seed_payload)}[args.block]
    rows = []
    for family in families:
        for repetition in range(args.start, args.start + args.repetitions):
            seed = generator(family, args.nodes, repetition)
            baseline = run_variant(seed, "public_greedy")
            candidate = run_search(seed, depth=args.depth, width=args.width,
                                   observation_slots=args.observation_slots, gate=args.gate)
            row = {"family": family, "repetition": repetition, "baseline": baseline,
                   "candidate": candidate, "delta": candidate["score"] - baseline["score"]}
            rows.append(row)
            print(json.dumps(row), flush=True)
    means = {family: statistics.mean(row["delta"] for row in rows if row["family"] == family) for family in families}
    report = {"config": {**vars(args), "output": str(args.output)}, "rows": rows,
              "family_mean_delta": means, "mean_delta": statistics.mean(row["delta"] for row in rows),
              "all_family_means_nonnegative": all(value >= -1e-8 for value in means.values()),
              "platform_score": None, "promotion_allowed": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}), flush=True)


if __name__ == "__main__":
    main()

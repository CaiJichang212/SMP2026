#!/usr/bin/env python3
"""P7 paired public-state response-stress screen; never a platform score."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from pathlib import Path
import statistics
import time

try:
    from scripts.run_budget_search import run_search
    from scripts.run_local_policy_matrix import (
        HOLDOUT_FAMILIES, INDEPENDENT_FAMILIES, LocalPublicEnvironment,
        holdout_seed_payload, independent_seed_payload, run_variant,
    )
except ModuleNotFoundError:
    from run_budget_search import run_search
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
from starnet.policy.robust_experiment import GATE_MODES, assess_structure
from starnet.policy.structural import ExperimentalPublicGreedyPlanner, public_positive_graph_gate_closed
from starnet.runtime.env_adapter import apply_action_outcome


BLOCKS = {
    "existing": (tuple(SEED_SPECS), seed_payload),
    "independent": (INDEPENDENT_FAMILIES, independent_seed_payload),
    "holdout": (HOLDOUT_FAMILIES, holdout_seed_payload),
}


def _public_state_key(
    board: Blackboard, budget: float, remaining_steps: int,
    first_responses: dict[int, float],
) -> tuple:
    return (
        tuple((node_id, node.w, node.persona, node.comm_left)
              for node_id, node in sorted(board.nodes.items())),
        tuple(sorted(board.edges)), tuple(sorted(first_responses.items())),
        budget, remaining_steps,
    )


def run_robust(
    seed: dict, *, mode: str, plan_cache: dict[tuple, object] | None = None,
    env_factory: Callable[[dict], object] = LocalPublicEnvironment,
) -> dict:
    """Execute one public-only robust arm; hidden response stays inside env."""
    if mode not in GATE_MODES:
        raise ValueError("unknown robust mode")
    started = time.perf_counter()
    env = env_factory(seed)
    count = len(seed["nodes"])
    board = Blackboard(node_count=count)
    actions = dict.fromkeys(("scan", "comm", "cut", "shield"), 0)
    first_responses: dict[int, float] = {}
    failures = steps = proposed = accepted = 0
    limit = 117 if count <= 50 else 247

    for node_id in range(1, count + 1):
        action = Action("scan", node_id)
        budget = env.get_remaining_budget()
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal scan")
        outcome = apply_action_outcome(env, board, action, budget)
        actions["scan"] += 1
        steps += 1
        if not outcome.succeeded:
            raise RuntimeError("scan failed")

    cache = plan_cache if plan_cache is not None else {}
    planning_seconds = 0.0
    while steps < limit:
        budget = env.get_remaining_budget()
        positive_graph = public_positive_graph_gate_closed(board)
        estimate = _response if positive_graph else public_response
        response_fn = lambda node_id, node, turn: estimate(
            node_id, node.persona, turn, first_responses, DEFAULT_CALIBRATION_PROFILE,
        )
        fallback = ExperimentalPublicGreedyPlanner(
            response_fn, candidate_limit=24, min_observed_responses=0,
            structure_roi_margin=1.0,
        ).candidates(board, budget, observed_response_count=len(first_responses))
        if not fallback:
            break
        action = fallback[0].action
        # P6's public-positive gate guarantees that no structure can be
        # proposed on this graph, so only mixed graphs need the search.
        if not positive_graph:
            key = _public_state_key(board, budget, limit - steps, first_responses)
            proposal = cache.get(key)
            if proposal is None:
                plan_started = time.perf_counter()
                proposal = budget_plan(
                    board, budget, response_fn, remaining_steps=limit - steps,
                    depth=2, width=4,
                )
                planning_seconds += time.perf_counter() - plan_started
                cache[key] = proposal
            if proposal.actions and proposal.actions[0].kind in {"cut", "shield"}:
                proposed += 1
                assessment = assess_structure(
                    board, budget, limit - steps, first_responses, proposal, mode=mode,
                )
                if assessment.accepted:
                    action = proposal.actions[0]
                    accepted += 1
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal robust action")
        old_w = board.nodes[action.target_node_1].w
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        actions[action.kind] += 1
        steps += 1
        if not outcome.succeeded:
            failures += 1
            break
        if action.kind == "comm":
            first_responses.setdefault(
                action.target_node_1,
                (board.nodes[action.target_node_1].w - old_w) / (0.5 ** (turn - 1)),
            )
    return {
        "score": env.evaluate(), "actions": actions, "failures": failures,
        "remaining_budget": env.get_remaining_budget(), "steps": steps,
        "structure_proposed": proposed, "structure_accepted": accepted,
        "planning_seconds": planning_seconds, "plan_cache_entries": len(cache),
        "seconds": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=tuple(BLOCKS), required=True)
    parser.add_argument("--start", type=int, default=301)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    allowed = range(401, 406) if args.confirm else range(301, 304)
    if args.repetitions < 1 or args.start not in allowed or args.start + args.repetitions - 1 not in allowed:
        parser.error("development uses 301-303; --confirm explicitly selects reserved 401-405")
    families, generator = BLOCKS[args.block]
    rows = []
    for family in families:
        for repetition in range(args.start, args.start + args.repetitions):
            seed = generator(family, 50, repetition)
            plan_cache: dict[tuple, object] = {}
            results = {
                "public_greedy": run_variant(seed, "public_greedy"),
                "p6_depth2": run_search(seed, depth=2, width=4),
                "strict": run_robust(seed, mode="strict", plan_cache=plan_cache),
                "bounded": run_robust(seed, mode="bounded", plan_cache=plan_cache),
            }
            for arm in ("p6_depth2", "strict", "bounded"):
                row = {
                    "family": family, "repetition": repetition, "variant": arm,
                    "baseline": results["public_greedy"], "candidate": results[arm],
                    "delta": results[arm]["score"] - results["public_greedy"]["score"],
                }
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)

    summary = {}
    for arm in ("p6_depth2", "strict", "bounded"):
        arm_rows = [row for row in rows if row["variant"] == arm]
        deltas = [row["delta"] for row in arm_rows]
        family_means = {
            family: statistics.mean(row["delta"] for row in arm_rows if row["family"] == family)
            for family in families
        }
        summary[arm] = {
            "mean_delta": statistics.mean(deltas),
            "family_mean_delta": family_means,
            "all_family_means_nonnegative": all(delta >= -1e-8 for delta in family_means.values()),
            "win_tie_loss": [sum(delta > 1e-8 for delta in deltas),
                             sum(abs(delta) <= 1e-8 for delta in deltas),
                             sum(delta < -1e-8 for delta in deltas)],
            "failures": sum(row["candidate"]["failures"] for row in arm_rows),
            "budget_and_steps_valid": all(
                row["candidate"]["remaining_budget"] >= 0
                and row["candidate"]["steps"] <= 117 for row in arm_rows
            ),
        }
    report = {
        "config": {"block": args.block, "start": args.start, "repetitions": args.repetitions,
                   "confirm": args.confirm, "node_count": 50, "depth": 2, "width": 4,
                   "scenario_first_responses": [3.0, 12.75, 22.5],
                   "strict_min_delta": 0.0, "bounded_min_delta": -5.0},
        "rows": rows, "summary": summary, "platform_score": None,
        "production_enabled": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

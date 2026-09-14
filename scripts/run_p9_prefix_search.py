#!/usr/bin/env python3
"""Run the preregistered depth-two structural-prefix attribution."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p8_search import run_p8, seed_hash
from starnet.experiments.p8_seeds import DEVELOPMENT_REPETITIONS, FAMILIES, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.p8_experiment import public_board_salt
from starnet.policy.p9_prefix_experiment import PrefixCache, PrefixMode, choose_prefix_action
from starnet.runtime.env_adapter import apply_action_outcome


FROZEN_FAMILIES = (
    "ba_negative_hubs",
    "sbm_violent_cluster",
    "double_bridge_communities",
    "bipartite",
)


def _action_payload(action: Action) -> dict[str, Any]:
    return {
        "kind": action.kind,
        "target_node_1": action.target_node_1,
        "target_node_2": action.target_node_2,
        "prompt_id": action.prompt_id,
    }


def run_prefix(seed: dict[str, Any], mode: PrefixMode):
    env = LocalPublicEnvironment(seed)
    count = len(seed["nodes"])
    board = Blackboard(node_count=count)
    observed: dict[int, float] = {}
    cache: PrefixCache = {}
    steps = failures = planning_calls = rollouts = 0
    collaborative_opportunities = accepted_prefixes = 0
    decisions = []
    limit = 117
    for node_id in range(1, count + 1):
        action = Action("scan", node_id)
        budget = env.get_remaining_budget()
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal prefix scan")
        if not apply_action_outcome(env, board, action, budget).succeeded:
            raise RuntimeError("prefix scan failed")
        steps += 1
    salt = public_board_salt(board)
    while steps < limit:
        decision = choose_prefix_action(
            board,
            env.get_remaining_budget(),
            observed,
            remaining_steps=limit - steps,
            salt=salt,
            mode=mode,
            evaluation_cache=cache,
        )
        planning_calls += 1
        rollouts += decision.rollouts
        collaborative_opportunities += int(decision.collaborative)
        accepted_prefixes += int(decision.accepted)
        if decision.collaborative:
            first = decision.proposed_prefix[:1]
            first_deltas = (decision.selection_deltas + decision.audit_deltas
                            if mode == "first" else decision.counterfactual_deltas)
            full_deltas = (decision.counterfactual_deltas
                           if mode == "first" else decision.selection_deltas + decision.audit_deltas)
            decisions.append({
                "step": steps + 1,
                "accepted": decision.accepted,
                "proposed_prefix": [_action_payload(action) for action in decision.proposed_prefix],
                "executed_sequence": [_action_payload(action) for action in decision.actions],
                "baseline_action": _action_payload(decision.baseline_action),
                "first_mean_delta": statistics.fmean(first_deltas),
                "full_mean_delta": statistics.fmean(full_deltas),
                "synergy_mean_delta": statistics.fmean(full_deltas) - statistics.fmean(first_deltas),
                "first_action": _action_payload(first[0]),
            })
        if not decision.actions:
            break
        for action in decision.actions:
            if steps >= limit:
                raise RuntimeError("accepted prefix exceeds real step limit")
            budget = env.get_remaining_budget()
            if not is_legal_action(action, board, budget):
                raise RuntimeError("illegal real prefix action")
            old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
            turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
            outcome = apply_action_outcome(env, board, action, budget)
            steps += 1
            if not outcome.succeeded:
                failures += 1
                break
            if action.kind == "comm" and turn == 1:
                observed[action.target_node_1] = board.nodes[action.target_node_1].w - old_w
        if failures:
            break
    return {
        "score": env.evaluate(),
        "actions": {kind: sum(call[0] == kind for call in env.calls)
                    for kind in ("scan", "comm", "cut", "shield")},
        "action_sequence": env.calls,
        "remaining_budget": env.get_remaining_budget(),
        "steps": steps,
        "failures": failures,
        "planning_calls": planning_calls,
        "rollouts": rollouts,
        "collaborative_opportunities": collaborative_opportunities,
        "accepted_prefixes": accepted_prefixes,
        "decisions": decisions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("diagnostic4-501", "old22-501", "old22-502-503"),
        default="diagnostic4-501",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    families = FROZEN_FAMILIES if args.stage == "diagnostic4-501" else FAMILIES
    repetitions = (501,) if args.stage != "old22-502-503" else (502, 503)
    if not set(repetitions).issubset(DEVELOPMENT_REPETITIONS):
        parser.error("P10 prefix stages use consumed P8 development repetitions only")
    config = {
        "schema_version": 1,
        "protocol": "p10-structure-prefix-development-20260914",
        "stage": args.stage,
        "families": list(families),
        "repetitions": list(repetitions),
        "policy_sha256": hashlib.sha256(
            (ROOT / "src/starnet/policy/p9_prefix_experiment.py").read_bytes()
        ).hexdigest(),
        "p8_policy_sha256": hashlib.sha256(
            (ROOT / "src/starnet/policy/p8_experiment.py").read_bytes()
        ).hexdigest(),
    }
    progress_path = args.output.with_suffix(".progress.json")
    rows = []
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("config") != config:
            parser.error("existing progress has a different P10 prefix configuration")
        rows = list(progress.get("rows", []))
    completed = {(row["family"], row["repetition"]) for row in rows}
    for repetition in repetitions:
        for family in families:
            if (family, repetition) in completed:
                continue
            seed = seed_payload(family, repetition)
            p9_bounded = run_p8(seed, "conservative")
            first = run_prefix(seed, "first")
            full = run_prefix(seed, "full")
            row = {
                "family": family,
                "repetition": repetition,
                "seed_sha256": seed_hash(seed),
                "p9_bounded": p9_bounded,
                "first": first,
                "full": full,
                "first_minus_p9_bounded": first["score"] - p9_bounded["score"],
                "full_minus_p9_bounded": full["score"] - p9_bounded["score"],
                "full_minus_first": full["score"] - first["score"],
            }
            rows.append(row)
            completed.add((family, repetition))
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_path.write_text(json.dumps({"config": config, "rows": rows},
                                                ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
            print(json.dumps({
                "family": family,
                "repetition": repetition,
                "p9_bounded": p9_bounded["score"],
                "first": first["score"],
                "full": full["score"],
                "full_minus_p9_bounded": row["full_minus_p9_bounded"],
                "full_minus_first": row["full_minus_first"],
                "opportunities": full["collaborative_opportunities"],
                "accepted": full["accepted_prefixes"],
            }), flush=True)
    report = {
        "schema_version": 1,
        "protocol": "p10-structure-prefix-development-20260914",
        "config": config,
        "families": list(families),
        "repetitions": list(repetitions),
        "selection_scenarios": 5,
        "audit_scenarios": 8,
        "rows": rows,
        "summary": {
            "first_minus_p9_bounded_mean": statistics.fmean(
                row["first_minus_p9_bounded"] for row in rows
            ),
            "full_minus_p9_bounded_mean": statistics.fmean(
                row["full_minus_p9_bounded"] for row in rows
            ),
            "full_minus_first_mean": statistics.fmean(row["full_minus_first"] for row in rows),
            "collaborative_opportunities": sum(row["full"]["collaborative_opportunities"] for row in rows),
            "accepted_full_prefixes": sum(row["full"]["accepted_prefixes"] for row in rows),
            "failures": sum(row[arm]["failures"] for row in rows
                            for arm in ("p9_bounded", "first", "full")),
            "win_tie_loss_vs_p9_bounded": [
                sum(row["full_minus_p9_bounded"] > 1e-8 for row in rows),
                sum(abs(row["full_minus_p9_bounded"]) <= 1e-8 for row in rows),
                sum(row["full_minus_p9_bounded"] < -1e-8 for row in rows),
            ],
        },
        "new_holdout_opened": False,
        "production_promotion_allowed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

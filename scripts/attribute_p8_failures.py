#!/usr/bin/env python3
"""Attribute three frozen P7 failures without opening new seed cohorts."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import LocalPublicEnvironment, run_variant
from scripts.run_rollout_search import run_search as run_rollout_search
from starnet.experiments.p7_seeds import seed_payload as p7_seed_payload
from starnet.experiments.seeds import seed_payload as existing_seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.baseline import _response, public_response
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.rollout_experiment import choose_rollout_action
from starnet.policy.structural import ExperimentalPublicGreedyPlanner, public_positive_graph_gate_closed
from starnet.runtime.env_adapter import apply_action_outcome


Case = tuple[str, int, str]
DEFAULT_CASES: tuple[Case, ...] = (
    ("er_balanced", 402, "existing"),
    ("lollipop", 301, "new"),
    ("bipartite", 303, "new"),
)


def _seed_for(case: Case) -> dict[str, Any]:
    family, repetition, source = case
    if repetition >= 601:
        raise ValueError("P8 attribution must not open repetition 601 or later")
    if source == "existing":
        return existing_seed_payload(family, 50, repetition)
    if source == "new":
        return p7_seed_payload(family, repetition, "standard")
    raise ValueError("unknown case source")


def _apply(env: Any, board: Blackboard, action: Action) -> tuple[float | None, bool]:
    budget = env.get_remaining_budget()
    if not is_legal_action(action, board, budget):
        raise RuntimeError("illegal replay action")
    old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
    outcome = apply_action_outcome(env, board, action, budget)
    if not outcome.succeeded:
        raise RuntimeError("public replay action failed")
    response = board.nodes[action.target_node_1].w - old_w if action.kind == "comm" else None
    return response, outcome.succeeded


def _replay_prefix(
    seed: dict[str, Any], history: tuple[Action, ...], env_factory: Callable[[dict], Any],
) -> tuple[Any, Blackboard, dict[int, float], int]:
    env = env_factory(seed)
    board = Blackboard(node_count=len(seed["nodes"]))
    steps = 0
    for node_id in range(1, len(seed["nodes"]) + 1):
        _apply(env, board, Action("scan", node_id))
        steps += 1
    observed: dict[int, float] = {}
    for action in history:
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        response, _ = _apply(env, board, action)
        steps += 1
        if action.kind == "comm" and turn == 1:
            assert response is not None
            observed[action.target_node_1] = response
    return env, board, observed, steps


def _public_greedy_action(
    board: Blackboard, budget: float, observed: dict[int, float],
) -> Action | None:
    estimate = _response if public_positive_graph_gate_closed(board) else public_response
    response_fn = lambda node_id, node, turn: estimate(
        node_id, node.persona, turn, observed, DEFAULT_CALIBRATION_PROFILE,
    )
    candidates = ExperimentalPublicGreedyPlanner(
        response_fn, candidate_limit=24, min_observed_responses=0,
        structure_roi_margin=1.0,
    ).candidates(board, budget, observed_response_count=len(observed))
    return candidates[0].action if candidates else None


def _forced_then_public_greedy(
    seed: dict[str, Any], history: tuple[Action, ...], first_action: Action,
    env_factory: Callable[[dict], Any],
) -> dict[str, Any]:
    env, board, observed, steps = _replay_prefix(seed, history, env_factory)
    limit = 117 if len(seed["nodes"]) <= 50 else 247
    actions = dict.fromkeys(("scan", "comm", "cut", "shield"), 0)
    actions["scan"] = len(seed["nodes"])
    for action in history:
        actions[action.kind] += 1
    pending: Action | None = first_action
    while steps < limit:
        action = pending
        pending = None
        if action is None:
            action = _public_greedy_action(board, env.get_remaining_budget(), observed)
        if action is None:
            break
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        response, _ = _apply(env, board, action)
        actions[action.kind] += 1
        steps += 1
        if action.kind == "comm" and turn == 1:
            assert response is not None
            observed[action.target_node_1] = response
    return {
        "score": env.evaluate(), "remaining_budget": env.get_remaining_budget(),
        "steps": steps, "actions": actions,
    }


def attribute_case(
    case: Case, *, env_factory: Callable[[dict], Any] = LocalPublicEnvironment,
) -> dict[str, Any]:
    """Replay one known failure and isolate its first divergent action."""
    seed = _seed_for(case)
    env, board, observed, steps = _replay_prefix(seed, (), env_factory)
    history: list[Action] = []
    divergence = None
    limit = 117
    while steps < limit:
        budget = env.get_remaining_budget()
        decision = choose_rollout_action(
            board, budget, observed, remaining_steps=limit - steps,
            scenario_count=1,
        )
        if decision.action is None:
            break
        if decision.action != decision.baseline_action:
            divergence = {
                "action_index_after_scan": len(history) + 1,
                "budget": budget,
                "candidate_action": asdict(decision.action),
                "baseline_action": asdict(decision.baseline_action),
                "predicted_scenario_deltas": list(decision.paired_deltas),
                "predicted_gain": (
                    sum(decision.paired_deltas) / len(decision.paired_deltas)
                    if decision.paired_deltas else 0.0
                ),
                "history": tuple(history),
            }
            break
        action = decision.action
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        response, _ = _apply(env, board, action)
        history.append(action)
        steps += 1
        if action.kind == "comm" and turn == 1:
            assert response is not None
            observed[action.target_node_1] = response
    if divergence is None:
        raise RuntimeError("known failure has no rollout divergence")

    prefix = divergence.pop("history")
    candidate_action = Action(**divergence["candidate_action"])
    baseline_action = Action(**divergence["baseline_action"])
    candidate_cf = _forced_then_public_greedy(
        seed, prefix, candidate_action, env_factory,
    )
    baseline_cf = _forced_then_public_greedy(
        seed, prefix, baseline_action, env_factory,
    )
    actual_gain = candidate_cf["score"] - baseline_cf["score"]
    predicted_gain = float(divergence["predicted_gain"])
    full_baseline = run_variant(seed, "public_greedy")
    full_candidate = run_rollout_search(seed, scenario_count=1, env_factory=env_factory)
    full_delta = full_candidate["score"] - full_baseline["score"]
    replanning_residual = full_delta - actual_gain
    first_action_error = actual_gain < -1e-8
    replanning_loss = replanning_residual < -1e-8
    if first_action_error and replanning_loss:
        attribution = "first_action_error_and_additional_replanning_loss"
    elif first_action_error and not replanning_loss:
        attribution = "first_action_response_model_error"
    elif not first_action_error and replanning_loss:
        attribution = "additional_replanning_loss"
    else:
        attribution = "no_attributed_loss"
    family, repetition, source = case
    return {
        "family": family, "repetition": repetition, "source": source,
        **divergence,
        "candidate_first_then_public_greedy": candidate_cf,
        "baseline_first_then_public_greedy": baseline_cf,
        "actual_counterfactual_gain": actual_gain,
        "prediction_error": actual_gain - predicted_gain,
        "full_baseline": full_baseline,
        "full_candidate": full_candidate,
        "full_delta": full_delta,
        "replanning_residual": replanning_residual,
        "first_action_response_model_error": first_action_error,
        "additional_replanning_loss": replanning_loss,
        "attribution": attribution,
        "policy_hidden_response_inputs": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [attribute_case(case) for case in DEFAULT_CASES]
    report = {
        "cases": rows,
        "case_limit": 3,
        "opened_repetitions": sorted({row["repetition"] for row in rows}),
        "repetition_601_or_later_opened": False,
        "environment": "LocalPublicEnvironment only",
        "production_enabled": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

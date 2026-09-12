#!/usr/bin/env python3
"""Screen a public-only guard against communicating a currently shieldable node."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping

from run_local_policy_matrix import (
    HOLDOUT_FAMILIES, INDEPENDENT_FAMILIES, LocalPublicEnvironment,
    holdout_seed_payload, independent_seed_payload,
)
from run_public_joint_structure_screen import _run_public_greedy_with_audit
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.baseline import _response, public_response
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.structural import ExperimentalPublicGreedyPlanner, public_positive_graph_gate_closed
from starnet.runtime.env_adapter import apply_action_outcome


def run_guarded(seed: Mapping[str, Any], *, guard_enabled: bool = True) -> dict[str, Any]:
    """Run current PUBLIC_GREEDY after excluding one locally dominated comm.

    The guard only excludes communication to a target for which the *current*
    scanned Blackboard already has a legal, strictly positive terminal-gain
    shield candidate.  It does not infer an unscanned edge, response factor,
    or final reward.
    """
    started = time.perf_counter()
    env = LocalPublicEnvironment(seed)
    board = Blackboard(node_count=len(seed["nodes"]))
    actions = {kind: 0 for kind in ("scan", "comm", "cut", "shield")}
    failures = 0
    for node_id in range(1, len(seed["nodes"]) + 1):
        outcome = apply_action_outcome(env, board, Action("scan", node_id), env.get_remaining_budget())
        actions["scan"] += 1
        failures += int(not outcome.succeeded)

    first_responses: dict[int, float] = {}
    suppressed_comm = 0
    max_steps = 117 if len(seed["nodes"]) <= 50 else 247
    for _ in range(max_steps):
        budget = env.get_remaining_budget()
        # Match RuntimeController exactly: the positive-graph gate retains
        # B1 pooled estimates, while all other public graphs use the fixed
        # untried population prior.
        response_fn = _response if public_positive_graph_gate_closed(board) else public_response
        planner = ExperimentalPublicGreedyPlanner(
            lambda node_id, node, turn: response_fn(
                node_id, node.persona, turn, first_responses, DEFAULT_CALIBRATION_PROFILE
            ),
            candidate_limit=24, min_observed_responses=0, structure_roi_margin=1.0,
        )
        candidates = planner.candidates(board, budget, observed_response_count=len(first_responses))
        shieldable = {
            candidate.action.target_node_1 for candidate in candidates
            if candidate.action.kind == "shield" and candidate.score > 0.0
        }
        filtered = [
            candidate for candidate in candidates
            if not (
                guard_enabled
                and candidate.action.kind == "comm"
                and candidate.action.target_node_1 in shieldable
            )
        ]
        suppressed_comm += len(candidates) - len(filtered)
        if not filtered:
            break
        action = filtered[0].action
        if not is_legal_action(action, board, budget):
            failures += 1
            break
        before_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        actions[action.kind] += 1
        if not outcome.succeeded:
            failures += 1
            break
        if action.kind == "comm" and before_w is not None:
            raw = outcome.raw_response
            assert isinstance(raw, dict)
            first_responses.setdefault(action.target_node_1, float(raw["new_w"]) - before_w)
    return {
        "score": env.evaluate(), "actions": actions, "failures": failures,
        "elapsed_seconds": time.perf_counter() - started,
        "remaining_budget": env.get_remaining_budget(), "suppressed_comm_candidates": suppressed_comm,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=("existing", "independent", "holdout"), required=True)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions <= 0:
        raise SystemExit("--repetitions must be positive")
    families = (
        SEED_SPECS if args.block == "existing"
        else INDEPENDENT_FAMILIES if args.block == "independent"
        else HOLDOUT_FAMILIES
    )
    make_seed = (
        seed_payload if args.block == "existing"
        else independent_seed_payload if args.block == "independent"
        else holdout_seed_payload
    )
    pairs: list[dict[str, Any]] = []
    for family in families:
        for repetition in range(1, args.repetitions + 1):
            seed = make_seed(family, 50, repetition)
            baseline = _run_public_greedy_with_audit(seed)
            # This is an internal causal check: disable only the exclusion and
            # require the independent runner to reproduce the controller.
            guard_off = run_guarded(seed, guard_enabled=False)
            equivalent = math.isclose(guard_off["score"], baseline["score"], abs_tol=1e-8)
            if not equivalent:
                raise RuntimeError(f"guard-off mismatch for {family} r{repetition}")
            guarded = run_guarded(seed)
            pairs.append({
                "family": family, "repetition": repetition,
                "public_greedy": baseline, "guard_disabled": guard_off,
                "guard_disabled_equivalent": equivalent,
                "comm_shield_guard": guarded,
                "delta": guarded["score"] - baseline["score"],
            })
    payload = {
        "schema_version": 1, "block": args.block, "node_count": 50, "repetitions": args.repetitions,
        "purpose": "local screen only; public-state guard, not submission evidence",
        "guard": "exclude a comm only when the same live target has a current legal positive-gain shield candidate",
        "pairs": pairs,
        "summary": {
            "mean_delta": sum(pair["delta"] for pair in pairs) / len(pairs),
            "wins": sum(pair["delta"] > 0 for pair in pairs),
            "ties": sum(pair["delta"] == 0 for pair in pairs),
            "losses": sum(pair["delta"] < 0 for pair in pairs),
            "failures": sum(pair["comm_shield_guard"]["failures"] for pair in pairs),
            "baseline_comm_then_shield": sum(pair["public_greedy"]["comm_then_shield"] for pair in pairs),
            "suppressed_candidates": sum(pair["comm_shield_guard"]["suppressed_comm_candidates"] for pair in pairs),
            "guard_disabled_equivalent": all(pair["guard_disabled_equivalent"] for pair in pairs),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Screen a public-only B4 joint-structure experiment against PUBLIC_GREEDY.

This is deliberately an offline experiment driver.  It uses only scan and
action-return data in its Blackboard; the local environment's response factor
is never read by the candidate.  The synthetic planning profile represents the
same public 12.75 first-response prior used by PUBLIC_GREEDY, rather than a
calibration suitable for submission promotion.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping

# When executed as ``python scripts/...`` Python places ``scripts`` itself on
# sys.path, so this sibling import deliberately has no package prefix.
from run_local_policy_matrix import (
    HOLDOUT_FAMILIES,
    INDEPENDENT_FAMILIES,
    LocalPublicEnvironment,
    holdout_seed_payload,
    independent_seed_payload,
)
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.baseline import public_response
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.cmg import PredictiveState
from starnet.policy.config import PolicyConfig, PolicyMode
from starnet.policy.structural import ExperimentalPublicGreedyPlanner, StructuralPlanner, public_positive_graph_gate_closed
from starnet.runtime.env_adapter import apply_action_outcome
from starnet.runtime.controller import RuntimeController


VARIANTS = ("public_greedy", "public_joint_structure")


def public_prior_profile() -> CalibrationProfile:
    """Return a locally valid planner profile using no hidden response data."""
    # 12.75 is the published local-screen population prior.  The response
    # ledger replaces it with a target's own returned response after success.
    means = {
        CalibrationProfile.response_key(persona, 1, turn): 12.75 * multiplier
        for persona in ("和平", "中立", "暴力")
        for turn, multiplier in ((1, 1.0), (2, 0.5), (3, 0.25))
    }
    draft = CalibrationProfile(
        gate_passed=True,
        structure_gate_passed=True,
        model="component_degree_plus_one",
        settlement_residual_std={"comm": 0.0, "cut": 0.0, "shield": 0.0},
        structure_action_residual_std={"comm": 0.0, "cut": 0.0, "shield": 0.0},
        response_mean=means,
        response_std={key: 0.0 for key in means},
        target_influence={"public_component": 1.0},
        manifest_hash="offline-public-prior-screen",
        data_hash="not-a-submission-calibration",
    )
    return CalibrationProfile(**{**asdict(draft), "profile_hash": draft.computed_hash()})


def _run_public_greedy_with_audit(seed: Mapping[str, Any]) -> dict[str, Any]:
    """Execute the current controller unchanged while retaining its call audit."""
    started = time.perf_counter()
    env = LocalPublicEnvironment(seed)
    config = PolicyConfig(
        policy_mode=PolicyMode.PUBLIC_GREEDY, enable_shield=True, enable_cut=True, max_llm_calls=0,
    )
    controller = RuntimeController(env, node_count=len(seed["nodes"]), initial_budget=env.get_remaining_budget(), config=config)
    while not controller.stopped:
        controller.step()
        if controller.step_number > config.safety_step_limit(len(seed["nodes"])) + 2:
            raise RuntimeError("local controller did not stop")
    previously_communicated: set[int] = set()
    comm_then_shield = 0
    for call in env.calls:
        if call[0] == "comm":
            previously_communicated.add(int(call[1]))
        elif call[0] == "shield" and int(call[1]) in previously_communicated:
            comm_then_shield += 1
    actions = {kind: sum(call[0] == kind for call in env.calls) for kind in ("scan", "comm", "cut", "shield")}
    return {
        "score": env.evaluate(), "actions": actions, "failures": controller.action_failures,
        "remaining_budget": env.get_remaining_budget(),
        "elapsed_seconds": time.perf_counter() - started, "planning_seconds": 0.0,
        "stop_reason": controller.stop_reason.value if controller.stop_reason else None,
        "comm_then_shield": comm_then_shield,
    }


def _run_public_joint_structure(seed: Mapping[str, Any]) -> dict[str, Any]:
    """Run PUBLIC_GREEDY with one bounded public pair-cut pre-screen.

    Full B4 replanning constructs a complete persuasion tail after every
    action and was too slow for a 50-node screen.  This candidate retains the
    deployable interaction that B4 adds: a pair whose two cuts help even
    though either singleton would be rejected.  It scores at most C(16, 2)
    pair states once, executes the selected legal pair, then resumes the
    current public greedy policy from returned public state.
    """
    started = time.perf_counter()
    env = LocalPublicEnvironment(seed)
    board = Blackboard(node_count=len(seed["nodes"]))
    failures = 0
    actions = {kind: 0 for kind in ("scan", "comm", "cut", "shield")}
    for node_id in range(1, len(seed["nodes"]) + 1):
        action = Action("scan", node_id)
        outcome = apply_action_outcome(env, board, action, env.get_remaining_budget())
        actions["scan"] += 1
        if not outcome.succeeded:
            failures += 1

    profile = public_prior_profile()
    planning_seconds = 0.0
    pair_cut_selected = False
    pair_cut_actions: list[str] = []
    # This is a one-time bounded interaction screen.  It sees only the
    # scanned Blackboard and never reads LocalPublicEnvironment private data.
    pair_planner = StructuralPlanner(
        profile, depth=2, width=1, candidate_limit=4,
        enable_pair_cut_experiment=True, pair_cut_edge_limit=16, pair_cut_plan_limit=1,
    )
    pair_started = time.perf_counter()
    sequences = pair_planner._pair_cut_sequences(  # noqa: SLF001 - experiment-only bounded probe
        PredictiveState.from_blackboard(board), env.get_remaining_budget()
    )
    planning_seconds += time.perf_counter() - pair_started
    if sequences:
        state = PredictiveState.from_blackboard(board)
        baseline = pair_planner._score(state)  # noqa: SLF001 - same experiment-only scorer
        chosen = sequences[0]
        if pair_planner._score(state.apply(chosen[0]).apply(chosen[1])) > baseline:  # noqa: SLF001
            for action in chosen:
                outcome = apply_action_outcome(env, board, action, env.get_remaining_budget())
                actions[action.kind] += 1
                if not outcome.succeeded:
                    failures += 1
                    break
                pair_cut_actions.append(f"{action.target_node_1}-{action.target_node_2}")
            pair_cut_selected = failures == 0

    response_estimates: dict[int, float] = {}
    steps = 0
    max_steps = 117 if len(seed["nodes"]) <= 50 else 247
    while steps < max_steps:
        budget = env.get_remaining_budget()
        response_fn = (lambda node_id, node, turn: public_response(
            node_id, node.persona, turn, response_estimates, DEFAULT_CALIBRATION_PROFILE
        ))
        planner = ExperimentalPublicGreedyPlanner(
            response_fn, candidate_limit=24, min_observed_responses=0, structure_roi_margin=1.0,
        )
        plan_started = time.perf_counter()
        candidates = planner.candidates(
            board, budget, observed_response_count=len(response_estimates),
        )
        planning_seconds += time.perf_counter() - plan_started
        if not candidates:
            break
        action = candidates[0].action
        # This duplicate preflight is intentional: an invalid structural call
        # costs budget in the official environment, so it must never be sent.
        if not is_legal_action(action, board, budget):
            failures += 1
            break
        before_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
        persona = board.nodes[action.target_node_1].persona if action.kind == "comm" else None
        turn = 4 - int(board.nodes[action.target_node_1].comm_left or 0) if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        actions[action.kind] += 1
        steps += 1
        if not outcome.succeeded:
            failures += 1
            break
        if action.kind == "comm" and before_w is not None and persona is not None:
            response = outcome.raw_response
            assert isinstance(response, dict)
            response_estimates.setdefault(action.target_node_1, float(response["new_w"]) - before_w)
    return {
        "score": env.evaluate(),
        "actions": actions,
        "failures": failures,
        "remaining_budget": env.get_remaining_budget(),
        "elapsed_seconds": time.perf_counter() - started,
        "planning_seconds": planning_seconds,
        "pair_cut_selected": pair_cut_selected,
        "pair_cut_actions": pair_cut_actions,
        "stop_reason": "step_limit" if steps >= max_steps else "no_positive_plan",
    }


def _families(block: str) -> tuple[Mapping[str, int] | tuple[str, ...], Callable[..., dict[str, Any]]]:
    if block == "existing":
        return SEED_SPECS, seed_payload
    if block == "independent":
        return INDEPENDENT_FAMILIES, independent_seed_payload
    return HOLDOUT_FAMILIES, holdout_seed_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=("existing", "independent", "holdout"))
    parser.add_argument("--families", nargs="+", help="Optional family subset for a bounded diagnostic run.")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions <= 0:
        raise SystemExit("--repetitions must be positive")

    blocks = (args.block,) if args.block else ("existing", "independent", "holdout")
    rows: list[dict[str, Any]] = []
    for block in blocks:
        families, make_seed = _families(block)
        selected_families = tuple(args.families) if args.families else tuple(families)
        unknown = set(selected_families).difference(families)
        if unknown:
            raise SystemExit(f"families do not belong to {block}: {sorted(unknown)}")
        for family in selected_families:
            for repetition in range(1, args.repetitions + 1):
                seed = make_seed(family, 50, repetition)
                for variant in VARIANTS:
                    started = time.perf_counter()
                    result = (
                        _run_public_greedy_with_audit(seed)
                        if variant == "public_greedy"
                        else _run_public_joint_structure(seed)
                    )
                    result.setdefault("elapsed_seconds", time.perf_counter() - started)
                    result.setdefault("planning_seconds", 0.0)
                    rows.append({
                        "block": block, "family": family, "node_count": 50,
                        "repetition": repetition, "variant": variant, **result,
                    })

    paired: list[dict[str, Any]] = []
    for block in blocks:
        all_families = _families(block)[0]
        selected_families = tuple(args.families) if args.families else tuple(all_families)
        for family in selected_families:
            for repetition in range(1, args.repetitions + 1):
                pair = [row for row in rows if row["block"] == block and row["family"] == family and row["repetition"] == repetition]
                baseline = next(row for row in pair if row["variant"] == "public_greedy")
                candidate = next(row for row in pair if row["variant"] == "public_joint_structure")
                paired.append({
                    "block": block, "family": family, "repetition": repetition,
                    "public_greedy_score": baseline["score"],
                    "joint_structure_score": candidate["score"],
                    "delta": candidate["score"] - baseline["score"],
                    "public_greedy_failures": baseline["failures"],
                    "joint_structure_failures": candidate["failures"],
                    "public_greedy_elapsed_seconds": baseline["elapsed_seconds"],
                    "joint_structure_elapsed_seconds": candidate["elapsed_seconds"],
                    "joint_structure_planning_seconds": candidate["planning_seconds"],
                    "public_greedy_comm_then_shield": baseline.get("comm_then_shield", 0),
                })
    payload = {
        "schema_version": 1,
        "purpose": "local-only paired screen; not leaderboard evidence or a promotion gate",
        "node_count": 50,
        "blocks": list(blocks),
        "repetitions": args.repetitions,
        "candidate": {
            "planner": "PUBLIC_GREEDY plus one bounded 16-edge pair-cut interaction pre-screen",
            "public_inputs": ["scan_node", "get_remaining_budget", "action return values"],
            "hidden_fields_read": [],
            "response_prior": "12.75 first slot, then own returned response × published marginal multipliers",
        },
        "rows": rows,
        "paired": paired,
        "summary": {
            "mean_delta": sum(item["delta"] for item in paired) / max(1, len(paired)),
            "wins": sum(item["delta"] > 0.0 for item in paired),
            "ties": sum(item["delta"] == 0.0 for item in paired),
            "losses": sum(item["delta"] < 0.0 for item in paired),
            "joint_failures": sum(item["joint_structure_failures"] for item in paired),
            "public_greedy_comm_then_shield": sum(item["public_greedy_comm_then_shield"] for item in paired),
            "mean_joint_elapsed_seconds": sum(item["joint_structure_elapsed_seconds"] for item in paired) / max(1, len(paired)),
            "mean_joint_planning_seconds": sum(item["joint_structure_planning_seconds"] for item in paired) / max(1, len(paired)),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

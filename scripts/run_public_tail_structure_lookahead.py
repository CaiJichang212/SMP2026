#!/usr/bin/env python3
"""Screen one public structure action plus a greedy communication tail.

This is a local experiment driver.  It uses copied public state to compare a
communication-only tail with each currently legal structure action followed
by the same communication allocator.  The comparison is repeated after every
real action response; no environment-private field is read.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from scripts.run_local_policy_matrix import (
        INDEPENDENT_FAMILIES,
        LocalPublicEnvironment,
        independent_seed_payload,
        run_variant,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from run_local_policy_matrix import (  # type: ignore[no-redef]
        INDEPENDENT_FAMILIES,
        LocalPublicEnvironment,
        independent_seed_payload,
        run_variant,
    )
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.baseline import _response, public_response
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.cmg import PredictiveState
from starnet.policy.structural import (
    ExperimentalPublicGreedyPlanner,
    public_positive_graph_gate_closed,
)
from starnet.runtime.env_adapter import apply_action_outcome


ResponseFn = Callable[[int, Any, int], float]


def _planner(response_fn: ResponseFn, candidate_limit: int) -> ExperimentalPublicGreedyPlanner:
    return ExperimentalPublicGreedyPlanner(
        response_fn,
        candidate_limit=candidate_limit,
        min_observed_responses=0,
        structure_roi_margin=1.0,
    )


def _project_comm_tail(
    state: PredictiveState,
    budget: float,
    response_fn: ResponseFn,
) -> float:
    """Project a communication tail without storing predictions in Blackboard."""
    predictor = _planner(response_fn, 1).predictor
    while budget >= action_cost(Action("comm", 1, prompt_id=1)):
        adjacency = {node_id: set() for node_id in state.nodes}
        for left, right in state.edges:
            if left in adjacency and right in adjacency:
                adjacency[left].add(right)
                adjacency[right].add(left)
        coefficients: dict[int, float] = {}
        unseen = set(state.nodes)
        while unseen:
            start = min(unseen)
            component: list[int] = []
            stack = [start]
            unseen.remove(start)
            while stack:
                node_id = stack.pop()
                component.append(node_id)
                for neighbor in adjacency[node_id]:
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        stack.append(neighbor)
            denominator = sum(len(adjacency[node_id]) + 1 for node_id in component)
            factor = len(component) / denominator
            coefficients.update({
                node_id: factor * (len(adjacency[node_id]) + 1)
                for node_id in component
            })
        choices: list[tuple[float, str, Action, float]] = []
        for node_id, node in sorted(state.nodes.items()):
            if node.comm_left <= 0:
                continue
            turn = 4 - node.comm_left
            if turn not in (1, 2, 3):
                continue
            delta = float(response_fn(node_id, node, turn))
            if delta <= 0.0:
                continue
            candidate_id = f"comm:{node_id}:{turn}"
            gain = coefficients.get(node_id, 0.0) * delta
            choices.append((-gain, candidate_id, Action("comm", node_id, prompt_id=1), delta))
        if not choices:
            break
        _, _, action, delta = min(choices)
        state = state.apply(action, delta)
        budget -= action_cost(action)
    return predictor.score(state)


def _lookahead_structure(
    board: Blackboard,
    budget: float,
    response_fn: ResponseFn,
    candidates: list[Any],
    candidate_limit: int,
) -> Any | None:
    initial = PredictiveState.from_blackboard(board)
    communication_terminal = _project_comm_tail(initial, budget, response_fn)
    best: tuple[float, str, Any] | None = None
    for candidate in candidates:
        action = candidate.action
        if action.kind not in {"cut", "shield"}:
            continue
        terminal = _project_comm_tail(
            initial.apply(action),
            budget - action_cost(action),
            response_fn,
        )
        key = (terminal, candidate.candidate_id, candidate)
        if best is None or terminal > best[0] or (
            terminal == best[0] and candidate.candidate_id < best[1]
        ):
            best = key
    if best is None or best[0] <= communication_terminal + 1.0e-9:
        return None
    return best[2]


def run_lookahead(
    seed: Mapping[str, Any],
    *,
    budget_low: float,
    budget_high: float,
    candidate_limit: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    env = LocalPublicEnvironment(seed)
    board = Blackboard(node_count=len(seed["nodes"]))
    actions = {kind: 0 for kind in ("scan", "comm", "cut", "shield")}
    failures = triggers = 0
    for node_id in range(1, len(seed["nodes"]) + 1):
        outcome = apply_action_outcome(
            env, board, Action("scan", node_id), env.get_remaining_budget()
        )
        actions["scan"] += 1
        failures += int(not outcome.succeeded)

    first_responses: dict[int, float] = {}
    max_steps = 117 if len(seed["nodes"]) <= 50 else 247
    for _ in range(max_steps):
        budget = env.get_remaining_budget()
        estimate = _response if public_positive_graph_gate_closed(board) else public_response
        response_fn: ResponseFn = lambda node_id, node, turn: estimate(
            node_id,
            node.persona,
            turn,
            first_responses,
            DEFAULT_CALIBRATION_PROFILE,
        )
        planner = _planner(response_fn, candidate_limit)
        candidates = planner.candidates(
            board, budget, observed_response_count=len(first_responses)
        )
        if budget_low <= budget < budget_high:
            structure = _lookahead_structure(
                board, budget, response_fn, candidates, candidate_limit
            )
            if structure is not None:
                candidates = [structure]
                triggers += 1
        if not candidates:
            break
        action = candidates[0].action
        if not is_legal_action(action, board, budget):
            failures += 1
            break
        old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        actions[action.kind] += 1
        if not outcome.succeeded:
            failures += 1
            break
        if action.kind == "comm" and old_w is not None:
            raw = outcome.raw_response
            if isinstance(raw, Mapping) and isinstance(raw.get("new_w"), (int, float)):
                first_responses.setdefault(
                    action.target_node_1, float(raw["new_w"]) - old_w
                )
    return {
        "score": env.evaluate(),
        "actions": actions,
        "failures": failures,
        "triggers": triggers,
        "remaining_budget": env.get_remaining_budget(),
        "elapsed_seconds": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", nargs="+", choices=("existing", "independent"), default=("existing", "independent"))
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--budget-low", type=float, default=5.0)
    parser.add_argument("--budget-high", type=float, default=25.0)
    parser.add_argument("--candidate-limit", type=int, default=64)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions <= 0 or args.candidate_limit <= 0:
        raise SystemExit("repetitions and candidate-limit must be positive")
    if not 0.0 <= args.budget_low < args.budget_high:
        raise SystemExit("invalid budget interval")

    rows: list[dict[str, Any]] = []
    for block in args.blocks:
        families = SEED_SPECS if block == "existing" else INDEPENDENT_FAMILIES
        make_seed = seed_payload if block == "existing" else independent_seed_payload
        for family in families:
            for repetition in range(1, args.repetitions + 1):
                seed = make_seed(family, 50, repetition)
                baseline = run_variant(seed, "public_greedy")
                disabled = run_lookahead(
                    seed,
                    budget_low=1.0e9,
                    budget_high=1.0e9 + 1.0,
                    candidate_limit=args.candidate_limit,
                )
                disabled_equivalent = (
                    abs(disabled["score"] - baseline["score"]) <= 1.0e-8
                    and disabled["actions"] == baseline["actions"]
                    and disabled["failures"] == baseline["failures"]
                )
                if not disabled_equivalent:
                    raise RuntimeError(
                        f"lookahead-off runner mismatch for {block}/{family}/r{repetition}"
                    )
                candidate = run_lookahead(
                    seed,
                    budget_low=args.budget_low,
                    budget_high=args.budget_high,
                    candidate_limit=args.candidate_limit,
                )
                rows.append({
                    "block": block,
                    "family": family,
                    "repetition": repetition,
                    "public_greedy": baseline,
                    "lookahead_disabled": disabled,
                    "lookahead_disabled_equivalent": disabled_equivalent,
                    "tail_lookahead": candidate,
                    "delta": candidate["score"] - baseline["score"],
                })
    payload = {
        "schema_version": 1,
        "scope": "local public-API paired screen; not leaderboard evidence",
        "budget_interval": [args.budget_low, args.budget_high],
        "candidate_limit": args.candidate_limit,
        "repetitions": args.repetitions,
        "rows": rows,
        "summary": {
            "pairs": len(rows),
            "mean_delta": sum(row["delta"] for row in rows) / len(rows),
            "wins": sum(row["delta"] > 1.0e-9 for row in rows),
            "ties": sum(abs(row["delta"]) <= 1.0e-9 for row in rows),
            "losses": sum(row["delta"] < -1.0e-9 for row in rows),
            "triggers": sum(row["tail_lookahead"]["triggers"] for row in rows),
            "failures": sum(row["tail_lookahead"]["failures"] for row in rows),
            "lookahead_disabled_equivalent": all(
                row["lookahead_disabled_equivalent"] for row in rows
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

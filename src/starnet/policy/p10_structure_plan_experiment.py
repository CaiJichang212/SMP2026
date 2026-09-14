"""Development-only unrestricted search for complete intervention plans."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Literal, Mapping, MutableMapping

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.budget_experiment import BudgetPlan, communication_tail
from starnet.policy.cmg import PredictiveState
from starnet.policy.p8_experiment import (
    _ProjectedBoard,
    _action_key,
    _greedy_candidates,
    _response_fn,
    _state_digest,
)
from starnet.policy.p9_prefix_experiment import _rollout_prefix


PlanCache = MutableMapping[tuple[object, ...], float]
RiskMode = Literal["strict", "mean_audited"]


@dataclass(frozen=True)
class FullStructurePlan:
    structure_actions: tuple[Action, ...]
    persuasion_actions: tuple[Action, ...]
    predicted_score: float
    baseline_score: float
    root_actions: int
    expanded_states: int
    planning_seconds: float

    @property
    def actions(self) -> tuple[Action, ...]:
        return self.structure_actions + self.persuasion_actions

    @property
    def predicted_gain(self) -> float:
        return self.predicted_score - self.baseline_score


@dataclass(frozen=True)
class FullPlanDecision:
    actions: tuple[Action, ...]
    baseline_action: Action | None
    plan: FullStructurePlan | None
    selection_deltas: tuple[float, ...]
    audit_deltas: tuple[float, ...]
    accepted: bool
    rollouts: int


def _topology_key(state: PredictiveState) -> tuple[object, ...]:
    return (frozenset(state.nodes), frozenset(state.edges))


def _legal_structures(state: PredictiveState, budget: float, prefix: tuple[Action, ...]):
    board = _ProjectedBoard.from_state(state, len(state.nodes) + len(state.dead_nodes))
    cut_nodes = {
        node_id
        for action in prefix if action.kind == "cut"
        for node_id in (action.target_node_1, action.target_node_2)
        if node_id is not None
    }
    actions = [
        Action("shield", node_id)
        for node_id in sorted(state.nodes)
        if node_id not in cut_nodes
    ]
    actions.extend(
        Action("cut", left, target_node_2=right)
        for left, right in sorted(state.edges)
    )
    return tuple(action for action in actions if is_legal_action(action, board, budget))


def _apply_prefix(initial: PredictiveState, prefix: tuple[Action, ...], budget: float):
    state = initial
    available = budget
    for index, action in enumerate(prefix):
        projected = _ProjectedBoard.from_state(
            state, len(state.nodes) + len(state.dead_nodes),
        )
        if not is_legal_action(action, projected, available):
            return None
        if action.kind == "shield" and any(
            previous.kind == "cut" and action.target_node_1 in {
                previous.target_node_1, previous.target_node_2,
            }
            for previous in prefix[:index]
        ):
            return None
        state = state.apply(action)
        available -= action_cost(action)
    return state, available


def search_full_structure_plan(
    board: Blackboard,
    budget: float,
    observed: Mapping[int, float],
    *,
    remaining_steps: int,
    max_structures: int,
    beam_width: int,
    response_estimator: Callable[[int, object, int], float] | None = None,
) -> FullStructurePlan | None:
    """Search all legal root structures and bounded deeper topology states."""
    if (max_structures <= 0 or beam_width <= 0 or remaining_steps <= 0
            or not math.isfinite(budget) or budget < 0):
        raise ValueError("invalid full-plan search resources")
    started = time.perf_counter()
    initial = PredictiveState.from_blackboard(board)
    response_fn = response_estimator or _response_fn(board, observed)
    baseline = communication_tail(initial, budget, response_fn, remaining_steps)
    root = _legal_structures(initial, budget, ())
    beam = [(initial, (), budget)]
    best: tuple[float, tuple[object, ...], tuple[Action, ...], BudgetPlan] | None = None
    expanded_states = 0

    for _ in range(min(max_structures, remaining_steps)):
        by_topology: dict[tuple[object, ...], tuple[float, tuple[object, ...], PredictiveState,
                                                   tuple[Action, ...], float, BudgetPlan]] = {}
        for state, prefix, available in beam:
            for action in _legal_structures(state, available, prefix):
                next_prefix = prefix + (action,)
                next_state = state.apply(action)
                next_budget = available - action_cost(action)
                tail = communication_tail(
                    next_state, next_budget, response_fn,
                    remaining_steps - len(next_prefix),
                )
                expanded_states += 1
                action_key = tuple(_action_key(item) for item in next_prefix)
                row = (tail.score, action_key, next_state, next_prefix, next_budget, tail)
                key = _topology_key(next_state)
                previous = by_topology.get(key)
                if previous is None or (-row[0], row[1]) < (-previous[0], previous[1]):
                    by_topology[key] = row
                terminal = (tail.score, action_key, next_prefix, tail)
                if best is None or (-terminal[0], terminal[1]) < (-best[0], best[1]):
                    best = terminal
        ranked = sorted(by_topology.values(), key=lambda item: (-item[0], item[1]))
        beam = [(item[2], item[3], item[4]) for item in ranked[:beam_width]]
        if not beam:
            break

    if best is None or best[0] <= baseline.score + 1e-9:
        return None

    # One delete-or-exchange pass catches a useful replacement whose prefix
    # was pruned at an earlier beam depth. Every replacement is rescored by
    # its complete persuasion allocation.
    best_score, best_key, best_prefix, best_tail = best
    for drop in range(len(best_prefix)):
        retained = best_prefix[:drop] + best_prefix[drop + 1:]
        rebuilt = _apply_prefix(initial, retained, budget)
        if rebuilt is None:
            continue
        state, available = rebuilt
        candidates = (None, *_legal_structures(state, available, retained))
        for replacement in candidates:
            prefix = retained if replacement is None else retained + (replacement,)
            applied = _apply_prefix(initial, prefix, budget)
            if applied is None:
                continue
            candidate_state, candidate_budget = applied
            tail = communication_tail(
                candidate_state, candidate_budget, response_fn,
                remaining_steps - len(prefix),
            )
            expanded_states += 1
            key = tuple(_action_key(item) for item in prefix)
            if (-tail.score, key) < (-best_score, best_key):
                best_score, best_key, best_prefix, best_tail = tail.score, key, prefix, tail

    return FullStructurePlan(
        best_prefix,
        best_tail.actions,
        best_score,
        baseline.score,
        len(root),
        expanded_states,
        time.perf_counter() - started,
    )


def choose_full_plan(
    board: Blackboard,
    budget: float,
    observed: Mapping[int, float],
    *,
    remaining_steps: int,
    salt: str,
    max_structures: int,
    beam_width: int,
    risk_mode: RiskMode = "strict",
    proposed_plan: FullStructurePlan | None = None,
    evaluation_cache: PlanCache | None = None,
) -> FullPlanDecision:
    if risk_mode not in ("strict", "mean_audited"):
        raise ValueError("unknown P10 risk mode")
    ranked = _greedy_candidates(board, budget, observed)
    if not ranked or remaining_steps <= 0:
        return FullPlanDecision((), None, None, (), (), False, 0)
    baseline = ranked[0].action
    plan = proposed_plan or search_full_structure_plan(
        board, budget, observed, remaining_steps=remaining_steps,
        max_structures=max_structures, beam_width=beam_width,
    )
    if (plan is None or not plan.structure_actions
            or len(plan.structure_actions) > remaining_steps):
        return FullPlanDecision((baseline,), baseline, plan, (), (), False, 0)
    cache = evaluation_cache if evaluation_cache is not None else {}
    digest = _state_digest(board)
    observed_key = tuple(sorted((node, float(value)) for node, value in observed.items()))
    rollouts = 0

    def score(actions: tuple[Action, ...], scenario: int) -> float:
        nonlocal rollouts
        key = (
            "p10_full_plan", digest, float(budget), remaining_steps, observed_key, salt,
            tuple(_action_key(action) for action in actions), scenario,
        )
        if key not in cache:
            cache[key] = _rollout_prefix(
                board, budget, observed, actions, remaining_steps,
                scenario=scenario, salt=salt,
            )
            rollouts += 1
        return float(cache[key])

    baseline_actions = (baseline,)
    selection = tuple(
        score(plan.structure_actions, scenario) - score(baseline_actions, scenario)
        for scenario in range(5)
    )
    audit = tuple(
        score(plan.structure_actions, scenario) - score(baseline_actions, scenario)
        for scenario in range(5, 13)
    )
    accepted = sum(selection) > 1e-9 and sum(audit) > 1e-9
    if risk_mode == "strict":
        accepted = accepted and min(selection) >= -1e-9 and min(audit) >= -1e-9
    return FullPlanDecision(
        plan.structure_actions if accepted else baseline_actions,
        baseline,
        plan,
        selection,
        audit,
        accepted,
        rollouts,
    )


__all__ = [
    "FullPlanDecision", "FullStructurePlan", "PlanCache", "RiskMode",
    "choose_full_plan", "search_full_structure_plan",
]

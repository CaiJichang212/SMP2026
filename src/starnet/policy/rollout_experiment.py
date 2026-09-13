"""Offline P7: paired public-state rollout of bounded first actions.

Counterfactual boards below are private planner inputs, never environment
facts or fields on the live Blackboard. Unknown response factors are sampled
from the public population prior and revealed to the simulated planner only
after its corresponding successful communication.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from types import MappingProxyType
from typing import Mapping

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.baseline import _response, public_response
from starnet.policy.budget_experiment import budget_plan
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.cmg import PredictiveState, bounded_response_delta
from starnet.policy.structural import (
    ExperimentalPublicGreedyPlanner,
    public_positive_graph_gate_closed,
)


@dataclass(frozen=True)
class RolloutDecision:
    action: Action | None
    baseline_action: Action | None
    paired_deltas: tuple[float, ...]
    compared_actions: tuple[Action, ...]
    rollouts: int


@dataclass(frozen=True)
class _ProjectedNode:
    w: float
    persona: str
    comm_left: int | None


@dataclass(frozen=True)
class _ProjectedBoard:
    """Read-only planner protocol over hypothetical state, never facts."""

    nodes: Mapping[int, _ProjectedNode]
    edges: frozenset[tuple[int, int]]
    dead_nodes: frozenset[int]
    node_count: int

    @classmethod
    def from_state(cls, state: PredictiveState, node_count: int) -> "_ProjectedBoard":
        nodes = {node_id: _ProjectedNode(node.w, node.persona, node.comm_left)
                 for node_id, node in state.nodes.items()}
        return cls(MappingProxyType(nodes), frozenset(state.edges),
                   frozenset(state.dead_nodes), node_count)

    @property
    def scanned_ids(self) -> frozenset[int]:
        return frozenset(self.nodes) | self.dead_nodes

    @property
    def shielded_ids(self) -> frozenset[int]:
        return self.dead_nodes


def _response_fn(board: Blackboard | _ProjectedBoard, observed: Mapping[int, float]):
    estimate = _response if public_positive_graph_gate_closed(board) else public_response
    return lambda node_id, node, turn: estimate(
        node_id, node.persona, turn, observed, DEFAULT_CALIBRATION_PROFILE,
    )


def _greedy_candidates(board: Blackboard | _ProjectedBoard, budget: float, observed: Mapping[int, float]):
    # The larger limit retains every structure candidate for the initial
    # alternative screen; the planner's own ranking remains unchanged.
    planner = ExperimentalPublicGreedyPlanner(
        _response_fn(board, observed),
        candidate_limit=len(board.edges) + 2 * len(board.nodes) + 1,
        min_observed_responses=0,
        structure_roi_margin=1.0,
    )
    return planner.candidates(board, budget, observed_response_count=len(observed))


def _scenario_factor(node_id: int, scenario: int, scenario_count: int) -> float:
    if scenario_count == 1:
        return 0.85
    # Independent of experiment seed, topology, opinions, and environment r.
    return random.Random(20260912 + node_id * 1009 + scenario * 1000003).uniform(0.2, 1.5)


def _rollout(
    board: Blackboard, budget: float, observed: Mapping[int, float],
    first_action: Action, remaining_steps: int, *, scenario: int, scenario_count: int,
) -> float:
    state = PredictiveState.from_blackboard(board)
    visible = dict(observed)
    pending: Action | None = first_action
    predictor = ExperimentalPublicGreedyPlanner(lambda *_: 1.0).predictor
    for _ in range(remaining_steps):
        projected = _ProjectedBoard.from_state(state, board.node_count or len(board.nodes))
        if pending is None:
            candidates = _greedy_candidates(projected, budget, visible)
            if not candidates:
                break
            action = candidates[0].action
        else:
            action, pending = pending, None
        if not is_legal_action(action, projected, budget):
            raise ValueError("illegal rollout action")
        delta = None
        if action.kind == "comm":
            node = state.nodes[action.target_node_1]
            turn = 4 - node.comm_left
            first = visible.get(action.target_node_1)
            if first is None:
                nominal_first = 15.0 * _scenario_factor(
                    action.target_node_1, scenario, scenario_count,
                )
                first = bounded_response_delta(node.w, nominal_first)
                visible[action.target_node_1] = first
            delta = bounded_response_delta(node.w, first * (0.5 ** (turn - 1)))
            if turn == 1:
                visible[action.target_node_1] = first
        state = state.apply(action, delta)
        budget -= action_cost(action)
    return predictor.score(state)


def choose_rollout_action(
    board: Blackboard, budget: float, observed: Mapping[int, float],
    *, remaining_steps: int, scenario_count: int = 1, include_budget_plan: bool = True,
) -> RolloutDecision:
    """Select an alternative only for positive mean and no paired loss.

    At most three first actions and three common response scenarios are
    considered. All scenario factors remain inside `_rollout`; the policy
    receives only successful hypothetical responses along each path.
    """
    if scenario_count not in (1, 3) or remaining_steps < 0 or not math.isfinite(budget) or budget < 0:
        raise ValueError("invalid rollout limits")
    if remaining_steps == 0:
        return RolloutDecision(None, None, (), (), 0)
    ranked = _greedy_candidates(board, budget, observed)
    if not ranked:
        return RolloutDecision(None, None, (), (), 0)
    baseline = ranked[0].action
    if public_positive_graph_gate_closed(board):
        return RolloutDecision(baseline, baseline, (), (baseline,), 0)
    structures = [item for item in ranked if item.action.kind in {"cut", "shield"}]
    alternatives: list[Action] = []
    if include_budget_plan:
        plan = budget_plan(
            board, budget, _response_fn(board, observed),
            remaining_steps=remaining_steps, depth=1, width=2,
        )
        if plan.actions and plan.actions[0].kind in {"cut", "shield"}:
            alternatives.append(plan.actions[0])
    if structures:
        best_immediate = min(structures, key=lambda item: (-item.score, item.candidate_id)).action
        alternatives.append(best_immediate)
    compared = tuple(dict.fromkeys((baseline, *alternatives)))[:3]
    if len(compared) == 1:
        return RolloutDecision(baseline, baseline, (), compared, 0)
    scores = {
        action: tuple(_rollout(board, budget, observed, action, remaining_steps,
                               scenario=scenario, scenario_count=scenario_count)
                      for scenario in range(scenario_count))
        for action in compared
    }
    best_action = baseline
    best_mean = 0.0
    best_deltas: tuple[float, ...] = ()
    for action in compared[1:]:
        deltas = tuple(score - base for score, base in zip(scores[action], scores[baseline]))
        mean = sum(deltas) / scenario_count
        if min(deltas) >= -1e-9 and mean > best_mean + 1e-9:
            best_action, best_mean, best_deltas = action, mean, deltas
    return RolloutDecision(best_action, baseline, best_deltas, compared,
                           len(compared) * scenario_count)


__all__ = ["RolloutDecision", "choose_rollout_action"]

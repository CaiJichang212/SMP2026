"""Offline-only response-stress gate for a budget-complete structure plan."""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.budget_experiment import BudgetPlan, communication_tail
from starnet.policy.cmg import PredictiveState


SCENARIO_FIRST_RESPONSES = (3.0, 12.75, 22.5)
GATE_MODES = frozenset({"strict", "bounded"})


@dataclass(frozen=True)
class StructureAssessment:
    accepted: bool
    deltas: tuple[float, ...]
    structure_actions: tuple[Action, ...]


def _structure_prefix(actions: tuple[Action, ...]) -> tuple[Action, ...]:
    prefix: list[Action] = []
    for action in actions:
        if action.kind not in {"cut", "shield"}:
            break
        prefix.append(action)
    return tuple(prefix)


def assess_structure(
    board: Blackboard,
    budget: float,
    remaining_steps: int,
    first_responses: Mapping[int, float],
    proposal: BudgetPlan,
    *,
    mode: str,
) -> StructureAssessment:
    """Compare one P6 structure prefix with equal-resource persuasion tails.

    Unknown responses are scenario assumptions, never environment facts. The
    original Blackboard is only read; hypothetical actions use PredictiveState.
    """
    if mode not in GATE_MODES or not math.isfinite(budget) or budget < 0 or remaining_steps < 0:
        raise ValueError("invalid robust assessment configuration")
    prefix = _structure_prefix(proposal.actions)
    if not prefix or not is_legal_action(prefix[0], board, budget):
        return StructureAssessment(False, (), prefix)
    for response in first_responses.values():
        if not math.isfinite(float(response)) or float(response) < 0:
            raise ValueError("first responses must be finite and nonnegative")

    initial = PredictiveState.from_blackboard(board)
    changed = initial
    available = budget
    for action in prefix:
        cost = action_cost(action)
        if available < cost or action.target_node_1 not in changed.nodes:
            return StructureAssessment(False, (), prefix)
        if action.kind == "cut" and (
            action.target_node_2 is None
            or tuple(sorted((action.target_node_1, action.target_node_2))) not in changed.edges
        ):
            return StructureAssessment(False, (), prefix)
        changed = changed.apply(action)
        available -= cost
    if len(prefix) > remaining_steps:
        return StructureAssessment(False, (), prefix)

    deltas: list[float] = []
    for prior in SCENARIO_FIRST_RESPONSES:
        def response_fn(node_id: int, _node: object, turn: int) -> float:
            first = float(first_responses.get(node_id, prior))
            return first * (0.5 ** (turn - 1))

        control = communication_tail(
            initial, budget, response_fn, remaining_steps, include_actions=False,
        ).score
        candidate = communication_tail(
            changed, available, response_fn, remaining_steps - len(prefix),
            include_actions=False,
        ).score
        deltas.append(candidate - control)
    accepted = (
        min(deltas) >= -1e-9 if mode == "strict"
        else sum(deltas) / len(deltas) > 1e-9 and min(deltas) >= -5.0 - 1e-9
    )
    return StructureAssessment(accepted, tuple(deltas), prefix)


__all__ = ["GATE_MODES", "SCENARIO_FIRST_RESPONSES", "StructureAssessment", "assess_structure"]

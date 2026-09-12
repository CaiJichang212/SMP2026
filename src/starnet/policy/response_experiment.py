"""Public-response-only allocation experiments.

This module is deliberately separate from the submission controller.  It
compares a fixed population response prior with online, public-response
calibration while keeping topology actions out of scope.  A first response is
recorded only after ``communicate`` returns it; no seed or environment-private
coefficient is accepted by this API.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import math
from typing import Literal

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action


PriorMode = Literal["fixed", "pooled", "persona_shrunk"]

_FIRST_SLOT_PRIOR = 12.75
_PRIOR_STRENGTH = 3.0
_MULTIPLIER = {1: 1.0, 2: 0.5, 3: 0.25}


def _turn(comm_left: int | None) -> int | None:
    turn = 4 - comm_left if comm_left is not None else None
    return turn if turn in _MULTIPLIER else None


def public_influence(board: Blackboard) -> dict[int, float]:
    """Compute the exact component-local coefficient from scanned facts."""
    adjacency = {node_id: set() for node_id in board.nodes}
    for left, right in board.edges:
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    result: dict[int, float] = {}
    unseen = set(adjacency)
    while unseen:
        root = min(unseen)
        stack, component = [root], []
        unseen.remove(root)
        while stack:
            node_id = stack.pop()
            component.append(node_id)
            for neighbor in adjacency[node_id]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        denominator = sum(len(adjacency[node_id]) + 1 for node_id in component)
        if denominator:
            scale = len(component) / denominator
            result.update({node_id: scale * (len(adjacency[node_id]) + 1) for node_id in component})
    return result


@dataclass
class PublicResponseCalibrator:
    """Online first-response summaries keyed solely by public persona labels."""

    by_persona: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    pooled: list[float] = field(default_factory=list)
    first_by_node: dict[int, float] = field(default_factory=dict)

    def record_first(self, node_id: int, persona: str, before_w: float, new_w: float) -> bool:
        """Accept a finite public first-slot delta once for each node."""
        delta = float(new_w) - float(before_w)
        if (
            node_id in self.first_by_node
            or not isinstance(persona, str)
            or not math.isfinite(delta)
        ):
            return False
        self.first_by_node[node_id] = delta
        self.pooled.append(delta)
        self.by_persona[persona].append(delta)
        return True

    def estimate_first(self, persona: str, mode: PriorMode) -> float:
        """Estimate an untried first slot without treating a node's r as known."""
        if mode == "fixed" or not self.pooled:
            return _FIRST_SLOT_PRIOR
        values = self.pooled if mode == "pooled" else self.by_persona.get(persona, [])
        if not values:
            return _FIRST_SLOT_PRIOR
        # Shrink empirical means to the published population prior.  This is
        # intentionally a mean estimate, not an optimistic UCB: a response is
        # observed only after its action succeeds and cannot justify peeking.
        return max(0.0, (_PRIOR_STRENGTH * _FIRST_SLOT_PRIOR + sum(values)) / (_PRIOR_STRENGTH + len(values)))


@dataclass(frozen=True)
class ResponseChoice:
    action: Action
    turn: int
    expected_delta: float
    influence: float
    expected_gain: float
    source: str

    @property
    def roi(self) -> float:
        return self.expected_gain / action_cost(self.action)


class ResponseBudgetPlanner:
    """Re-rank every legal persuasion slot after each public response.

    Already tried nodes use their own public first response with the official
    1, 1/2, 1/4 multipliers.  Untried nodes use one of the explicit ablation
    priors.  Each call returns exactly one action, so the remaining budget is
    naturally respected by the caller's next invocation.
    """

    def __init__(self, *, prior_mode: PriorMode = "fixed") -> None:
        if prior_mode not in {"fixed", "pooled", "persona_shrunk"}:
            raise ValueError("unknown response prior mode")
        self.prior_mode = prior_mode
        self.calibrator = PublicResponseCalibrator()

    def observe_success(self, node_id: int, persona: str, before_w: float, new_w: float, turn: int) -> bool:
        if turn != 1:
            return False
        return self.calibrator.record_first(node_id, persona, before_w, new_w)

    def next_choice(self, board: Blackboard, budget: float) -> ResponseChoice | None:
        coefficients = public_influence(board)
        choices: list[ResponseChoice] = []
        for node_id, node in sorted(board.nodes.items()):
            turn = _turn(node.comm_left)
            action = Action("comm", node_id, prompt_id=1)
            if turn is None or not is_legal_action(action, board, budget):
                continue
            first = self.calibrator.first_by_node.get(node_id)
            if first is None:
                estimate = self.calibrator.estimate_first(node.persona, self.prior_mode)
                source = self.prior_mode
            else:
                estimate = max(0.0, first) * _MULTIPLIER[turn]
                source = "own_first_response"
            influence = coefficients.get(node_id, 0.0)
            gain = influence * estimate
            if math.isfinite(gain) and gain > 0.0:
                choices.append(ResponseChoice(action, turn, estimate, influence, gain, source))
        return min(
            choices,
            key=lambda item: (-round(item.roi, 12), -round(item.expected_gain, 12), item.action.target_node_1),
            default=None,
        )


__all__ = [
    "PriorMode", "PublicResponseCalibrator", "ResponseBudgetPlanner", "ResponseChoice", "public_influence",
]

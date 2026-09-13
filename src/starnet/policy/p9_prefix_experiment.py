"""Development-only evaluation of committed structural action prefixes."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Mapping, MutableMapping

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.budget_experiment import budget_plan
from starnet.policy.cmg import PredictiveState
from starnet.policy.p8_experiment import (
    _FAST_SETTLEMENT,
    _ProjectedBoard,
    _action_key,
    _greedy_candidates,
    _response_fn,
    _scenario_factor,
    _state_digest,
)


PrefixMode = Literal["first", "full"]
PrefixCache = MutableMapping[tuple[object, ...], float]


@dataclass(frozen=True)
class PrefixDecision:
    actions: tuple[Action, ...]
    baseline_action: Action | None
    proposed_prefix: tuple[Action, ...]
    selection_deltas: tuple[float, ...]
    audit_deltas: tuple[float, ...]
    counterfactual_deltas: tuple[float, ...]
    accepted: bool
    rollouts: int

    @property
    def collaborative(self) -> bool:
        return len(self.proposed_prefix) >= 2


def structural_prefix(
    board: Blackboard,
    budget: float,
    observed: Mapping[int, float],
    remaining_steps: int,
) -> tuple[Action, ...]:
    """Return only the consecutive structure prefix of the depth-two plan."""
    plan = budget_plan(
        board,
        budget,
        _response_fn(board, observed),
        remaining_steps=remaining_steps,
        depth=2,
        width=4,
    )
    prefix: list[Action] = []
    for action in plan.actions:
        if action.kind not in {"cut", "shield"}:
            break
        prefix.append(action)
    return tuple(prefix)


def _rollout_prefix(
    board: Blackboard,
    budget: float,
    observed: Mapping[int, float],
    prefix: tuple[Action, ...],
    remaining_steps: int,
    *,
    scenario: int,
    salt: str,
) -> float:
    """Apply a validated predicted prefix, then continue with public greedy."""
    if not prefix or remaining_steps < 0 or not math.isfinite(budget) or budget < 0:
        raise ValueError("invalid prefix rollout resources")
    state = PredictiveState.from_blackboard(board)
    visible = dict(observed)
    pending = list(prefix)
    for _ in range(remaining_steps):
        projected = _ProjectedBoard.from_state(state, board.node_count or len(board.nodes))
        if pending:
            action = pending.pop(0)
        else:
            candidates = _greedy_candidates(projected, budget, visible)
            if not candidates:
                break
            action = candidates[0].action
        if not is_legal_action(action, projected, budget):
            raise ValueError("illegal action in predicted prefix")
        delta = None
        if action.kind == "comm":
            node = state.nodes[action.target_node_1]
            if node.comm_left is None:
                raise ValueError("missing public communication count")
            turn = 4 - node.comm_left
            first = visible.get(action.target_node_1)
            if first is None:
                first = 15.0 * _scenario_factor(salt, action.target_node_1, scenario)
                visible[action.target_node_1] = first
            delta = first * (0.5 ** (turn - 1))
        state = state.apply(action, delta)
        budget -= action_cost(action)
    if pending:
        raise ValueError("prefix exceeds remaining step limit")
    score = float(_FAST_SETTLEMENT.score(state))
    if not math.isfinite(score):
        raise ValueError("nonfinite prefix rollout score")
    return score


def choose_prefix_action(
    board: Blackboard,
    budget: float,
    observed: Mapping[int, float],
    *,
    remaining_steps: int,
    salt: str,
    mode: PrefixMode,
    evaluation_cache: PrefixCache | None = None,
) -> PrefixDecision:
    """Compare first-only and full-prefix values with selection and audit pairs."""
    if mode not in ("first", "full"):
        raise ValueError("unknown prefix mode")
    if remaining_steps < 0 or not math.isfinite(budget) or budget < 0 or len(salt) != 64:
        raise ValueError("invalid prefix decision inputs")
    if any(not math.isfinite(float(value)) for value in observed.values()):
        raise ValueError("nonfinite public response")
    ranked = _greedy_candidates(board, budget, observed)
    if not ranked or remaining_steps == 0:
        return PrefixDecision((), None, (), (), (), (), False, 0)
    baseline = ranked[0].action
    proposed = structural_prefix(board, budget, observed, remaining_steps)
    if len(proposed) < 2:
        return PrefixDecision((baseline,), baseline, proposed, (), (), (), False, 0)

    first = proposed[:1]
    chosen = first if mode == "first" else proposed
    counterfactual = proposed if mode == "first" else first
    cache = evaluation_cache if evaluation_cache is not None else {}
    digest = _state_digest(board)
    observed_key = tuple(sorted((node, float(value)) for node, value in observed.items()))
    rollouts = 0

    def score(sequence: tuple[Action, ...], scenario: int) -> float:
        nonlocal rollouts
        key = (
            "p9_prefix", digest, float(budget), remaining_steps, observed_key, salt,
            tuple(_action_key(action) for action in sequence), scenario,
        )
        if key not in cache:
            cache[key] = _rollout_prefix(
                board, budget, observed, sequence, remaining_steps,
                scenario=scenario, salt=salt,
            )
            rollouts += 1
        return float(cache[key])

    baseline_sequence = (baseline,)
    selection = tuple(
        score(chosen, scenario) - score(baseline_sequence, scenario)
        for scenario in range(5)
    )
    audit = tuple(
        score(chosen, scenario) - score(baseline_sequence, scenario)
        for scenario in range(5, 13)
    )
    counterfactual_deltas = tuple(
        score(counterfactual, scenario) - score(baseline_sequence, scenario)
        for scenario in range(13)
    )
    accepted = (
        sum(selection) > 1e-9
        and min(selection) >= -1e-9
        and sum(audit) > 1e-9
        and min(audit) >= -1e-9
    )
    return PrefixDecision(
        chosen if accepted else baseline_sequence,
        baseline,
        proposed,
        selection,
        audit,
        counterfactual_deltas,
        accepted,
        rollouts,
    )


__all__ = [
    "PrefixCache",
    "PrefixDecision",
    "PrefixMode",
    "choose_prefix_action",
    "structural_prefix",
]

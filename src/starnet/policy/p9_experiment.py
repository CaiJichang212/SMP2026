"""Development-only expansion of P8's first-action candidate domain.

The module reuses P8's public-state projections and paired rollouts. It is not
imported by a runtime controller or submission build.
"""

from __future__ import annotations

import math
from typing import Literal, Mapping

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.budget_experiment import budget_plan
from starnet.policy.p8_experiment import (
    EvaluationCache,
    P8Decision,
    _action_key,
    _greedy_candidates,
    _response_fn,
    _rollout,
    _state_digest,
)


P9Variant = Literal["depth2", "portfolio"]


def _rank(items):
    return sorted(items, key=lambda item: (-item.roi, -item.score, item.candidate_id))


def candidate_domain(
    board: Blackboard,
    budget: float,
    observed: Mapping[int, float],
    remaining_steps: int,
    variant: P9Variant,
) -> tuple[tuple[Action, str], ...]:
    """Return a bounded, stable set of legal first actions from public facts."""
    if variant not in ("depth2", "portfolio"):
        raise ValueError("unknown P9 variant")
    ranked = _greedy_candidates(board, budget, observed)
    if not ranked:
        return ()
    candidates: list[tuple[Action, str]] = [(ranked[0].action, "public_greedy")]
    plan = budget_plan(
        board,
        budget,
        _response_fn(board, observed),
        remaining_steps=remaining_steps,
        depth=2,
        width=4,
    )
    if plan.actions and plan.actions[0].kind in {"cut", "shield"}:
        candidates.append((plan.actions[0], "depth2_budget_structure"))

    structures = [item for item in ranked if item.action.kind in {"cut", "shield"}]
    if variant == "depth2":
        if structures:
            best = min(structures, key=lambda item: (-item.score, item.candidate_id))
            candidates.append((best.action, "immediate_structure_gain"))
    else:
        for kind in ("shield", "cut"):
            by_kind = [item for item in structures if item.action.kind == kind]
            if by_kind:
                best = min(by_kind, key=lambda item: (-item.score, item.candidate_id))
                candidates.append((best.action, f"immediate_{kind}"))

    untried = _rank(
        item
        for item in ranked
        if item.action.kind == "comm" and item.action.target_node_1 not in observed
    )
    untried_limit = 1 if variant == "depth2" else 2
    candidates.extend((item.action, "untried_comm_roi") for item in untried[:untried_limit])
    if variant == "portfolio":
        known = _rank(
            item
            for item in ranked
            if item.action.kind == "comm" and item.action.target_node_1 in observed
        )
        existing = {action for action, _ in candidates}
        distinct = next((item for item in known if item.action not in existing), None)
        if distinct is not None:
            candidates.append((distinct.action, "observed_comm_roi"))

    unique: list[tuple[Action, str]] = []
    seen: set[Action] = set()
    for action, source in candidates:
        if action not in seen:
            seen.add(action)
            unique.append((action, source))
    return tuple(unique[:8])


def choose_p9_action(
    board: Blackboard,
    budget: float,
    observed: Mapping[int, float],
    *,
    remaining_steps: int,
    salt: str,
    variant: P9Variant,
    evaluation_cache: EvaluationCache | None = None,
) -> P8Decision:
    """Choose the best candidate with P8's five-scenario conservative rule."""
    if remaining_steps < 0 or not math.isfinite(budget) or budget < 0 or len(salt) != 64:
        raise ValueError("invalid P9 decision inputs")
    if any(not math.isfinite(float(value)) for value in observed.values()):
        raise ValueError("nonfinite public response")
    if remaining_steps == 0:
        return P8Decision(None, None, "none", (), (), 0.0, 0.0, 0)
    domain = candidate_domain(board, budget, observed, remaining_steps, variant)
    if not domain:
        return P8Decision(None, None, "none", (), (), 0.0, 0.0, 0)
    baseline = domain[0][0]
    if len(domain) == 1:
        return P8Decision(baseline, baseline, "public_greedy", (baseline,), (), 0.0, 0.0, 0)

    cache = evaluation_cache if evaluation_cache is not None else {}
    digest = _state_digest(board)
    observed_key = tuple(sorted((node, float(value)) for node, value in observed.items()))
    rollouts = 0

    def score(action: Action, scenario: int) -> float:
        nonlocal rollouts
        key = (
            "p9", digest, float(budget), remaining_steps, observed_key, salt,
            _action_key(action), scenario,
        )
        if key not in cache:
            cache[key] = _rollout(
                board, budget, observed, action, remaining_steps,
                scenario=scenario, salt=salt,
            )
            rollouts += 1
        value = float(cache[key])
        if not math.isfinite(value):
            raise ValueError("nonfinite cached P9 score")
        return value

    baseline_mean = score(baseline, 0)
    finalists: list[tuple[Action, str]] = []
    for action, source in domain[1:]:
        mean_delta = score(action, 0) - baseline_mean
        if action.kind == "comm" or mean_delta > 1e-9:
            finalists.append((action, source))
    accepted: list[tuple[float, tuple[object, ...], Action, str, tuple[float, ...]]] = []
    for action, source in finalists:
        deltas = tuple(score(action, scenario) - score(baseline, scenario) for scenario in range(5))
        if sum(deltas) > 1e-9 and min(deltas) >= -1e-9:
            accepted.append((-sum(deltas), _action_key(action), action, source, deltas))
    compared = tuple(action for action, _ in domain)
    if not accepted:
        return P8Decision(baseline, baseline, "public_greedy", compared, (), 0.0, 0.0, rollouts)
    _, _, winner, source, deltas = min(accepted)
    mean_delta = sum(deltas) / len(deltas)
    return P8Decision(
        winner, baseline, source, compared, deltas, mean_delta, min(deltas), rollouts,
        proposed_action=winner,
    )


__all__ = ["P9Variant", "candidate_domain", "choose_p9_action"]

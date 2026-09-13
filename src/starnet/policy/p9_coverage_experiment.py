"""Experimental recovery of profitable structure omitted by heuristic gates.

These actions are not directly authorized: only audited public-state terminal
rollouts may propose them. The frozen P8 action is the fallback throughout.
"""

from __future__ import annotations

from dataclasses import replace
from starnet.policy.p8_experiment import (
    P8Decision, _FAST_SETTLEMENT, _action_key, _greedy_candidates,
    _response_fn, _rollout, choose_p8_action,
)
from starnet.policy.structural import ExperimentalPublicGreedyPlanner


def excluded_structure_domain(board, budget, observed):
    """Keep at most four legal positive-gain actions absent from P8's domain."""
    admitted = {item.action for item in _greedy_candidates(board, budget, observed)}
    planner = ExperimentalPublicGreedyPlanner(
        _response_fn(board, observed), conservative_structure=False,
        candidate_limit=len(board.edges) + 2 * len(board.nodes) + 1,
    )
    planner.predictor = _FAST_SETTLEMENT
    unrestricted = planner.candidates(board, budget)
    domain = []
    for kind in ("shield", "cut"):
        items = [item for item in unrestricted
                 if item.action.kind == kind and item.action not in admitted]
        if not items:
            continue
        for best in (
            min(items, key=lambda item: (-item.score, item.candidate_id)),
            min(items, key=lambda item: (-item.roi, item.candidate_id)),
        ):
            if best.action not in domain:
                domain.append(best.action)
    return tuple(domain)


def choose_coverage_action(board, budget, observed, *, remaining_steps, salt,
                           mode="conservative", evaluation_cache=None):
    baseline = choose_p8_action(
        board, budget, observed, remaining_steps=remaining_steps, salt=salt,
        mode="conservative", evaluation_cache=evaluation_cache,
    )
    if baseline.action is None or remaining_steps == 0:
        return baseline
    domain = excluded_structure_domain(board, budget, observed)
    domain = tuple(action for action in domain if action != baseline.action)
    if not domain:
        return baseline
    scores = {}
    rollouts = baseline.rollouts

    def score(action, scenario):
        nonlocal rollouts
        key = action, scenario
        if key not in scores:
            scores[key] = _rollout(board, budget, observed, action, remaining_steps,
                                   scenario=scenario, salt=salt)
            rollouts += 1
        return scores[key]

    accepted = []
    for action in domain:
        if score(action, 0) <= score(baseline.action, 0) + 1e-9:
            continue
        deltas = tuple(score(action, scenario) - score(baseline.action, scenario)
                       for scenario in range(5))
        if sum(deltas) > 1e-9 and min(deltas) >= -1e-9:
            accepted.append((-sum(deltas), _action_key(action), action, deltas))
    if not accepted:
        return replace(baseline, rollouts=rollouts)
    _, _, winner, deltas = min(accepted)
    audit = tuple(score(winner, scenario) - score(baseline.action, scenario)
                  for scenario in range(5, 13))
    if sum(audit) <= 1e-9 or min(audit) < -1e-9:
        return replace(baseline, rollouts=rollouts)
    return P8Decision(
        winner, baseline.action, "audited_excluded_structure", (baseline.action,) + domain,
        deltas, sum(deltas) / 5, min(deltas), rollouts,
        proposed_action=winner, audit_paired_deltas=audit,
        audit_mean_delta=sum(audit) / 8, audit_minimum_delta=min(audit),
    )

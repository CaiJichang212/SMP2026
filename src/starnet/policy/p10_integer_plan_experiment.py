"""Experimental joint shield/persuasion candidates from a linear integer model.

The connected-graph fractional objective is only a candidate generator. Every
returned shield set is rescored by exact component settlement and public-state
rollouts; no assertion of global optimality or known hidden responses is made.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from starnet.policy.actions import Action
from starnet.policy.budget_experiment import communication_tail
from starnet.policy.cmg import PredictiveState, bounded_response_delta
from starnet.policy.p8_experiment import _response_fn, choose_p8_action
from starnet.policy.p9_prefix_experiment import _rollout_prefix


@dataclass(frozen=True)
class IntegerPlan:
    shields: tuple[Action, ...]
    predicted_score: float
    solver_status: int
    seconds: float


def integer_candidates(board, budget, observed, remaining_steps, *, seconds_per_solve=0.5):
    """Generate at most six legal shield sets; preserve adaptive persuasion."""
    state = PredictiveState.from_blackboard(board)
    nodes = sorted(state.nodes)
    edges = sorted(state.edges)
    response = _response_fn(board, observed)
    numer, denom = [], []

    def var(numerator, denominator=0.0):
        index = len(numer)
        numer.append(float(numerator))
        denom.append(float(denominator))
        return index

    alive = {node: var(state.nodes[node].w, 1) for node in nodes}
    retained = {edge: var(state.nodes[edge[0]].w + state.nodes[edge[1]].w, 2) for edge in edges}
    slots, deltas = {}, {}
    for node in nodes:
        item = state.nodes[node]
        opinion = item.w
        for turn in range(4 - int(item.comm_left or 0), 4):
            delta = bounded_response_delta(opinion, response(node, item, turn))
            if delta < 0 or not math.isfinite(delta):
                return ()
            opinion += delta
            slots[node, turn] = var(delta)
            deltas[node, turn] = delta
    row_ids, col_ids, values, lower, upper = [], [], [], [], []

    def constraint(coefficients, lo=-np.inf, hi=np.inf):
        row = len(lower)
        for column, coefficient in coefficients:
            row_ids.append(row)
            col_ids.append(column)
            values.append(coefficient)
        lower.append(lo)
        upper.append(hi)

    def conjunction(product, left, right):
        constraint(((product, 1), (left, -1)), hi=0)
        constraint(((product, 1), (right, -1)), hi=0)
        constraint(((product, 1), (left, -1), (right, -1)), lo=-1)

    for (left, right), edge_var in retained.items():
        conjunction(edge_var, alive[left], alive[right])
        for node in (left, right):
            for turn in range(4 - int(state.nodes[node].comm_left or 0), 4):
                conjunction(var(deltas[node, turn]), edge_var, slots[node, turn])
    for (node, turn), slot in slots.items():
        previous = slots.get((node, turn - 1), alive[node])
        constraint(((slot, 1), (previous, -1)), hi=0)
    alive_row = len(lower)
    constraint(((value, 1) for value in alive.values()), lo=0, hi=len(nodes))
    slot_row = len(lower)
    constraint(((value, 1) for value in slots.values()), hi=remaining_steps)
    matrix = coo_matrix((values, (row_ids, col_ids)), shape=(len(lower), len(numer))).tocsc()
    numer, denom = np.asarray(numer), np.asarray(denom)
    initial_mean = communication_tail(state, budget, response, remaining_steps).score / max(1, len(nodes))
    plans = {}
    for count in (1, 3, 5, 8, 12, 15):
        if count >= len(nodes) or count * 5 > budget or count >= remaining_steps:
            continue
        lo, hi = np.asarray(lower).copy(), np.asarray(upper).copy()
        lo[alive_row] = hi[alive_row] = len(nodes) - count
        hi[slot_row] = min(int((budget - count * 5) // 2), remaining_steps - count)
        ratio = initial_mean
        started = time.perf_counter()
        for _ in range(2):
            result = milp(
                c=-(numer - ratio * denom), integrality=np.ones(len(numer)),
                bounds=Bounds(np.zeros(len(numer)), np.ones(len(numer))),
                constraints=LinearConstraint(matrix, lo, hi),
                options={"time_limit": seconds_per_solve, "mip_rel_gap": 0.01},
            )
            if result.x is None:
                break
            rounded = np.rint(result.x)
            if np.max(np.abs(rounded - result.x)) > 1e-5:
                break
            feasible = matrix @ rounded
            if np.any(feasible < lo - 1e-6) or np.any(feasible > hi + 1e-6):
                break
            removed = tuple(node for node in nodes if rounded[alive[node]] < 0.5)
            if len(removed) != count:
                break
            changed = state
            shields = tuple(Action("shield", node) for node in removed)
            for action in shields:
                changed = changed.apply(action)
            tail = communication_tail(changed, budget - count * 5, response, remaining_steps - count)
            plans[removed] = IntegerPlan(shields, tail.score, int(result.status), time.perf_counter() - started)
            denominator = float(denom @ rounded)
            if denominator <= 0:
                break
            ratio = float(numer @ rounded) / denominator
    return tuple(sorted(plans.values(), key=lambda plan: (-plan.predicted_score, tuple(a.target_node_1 for a in plan.shields))))[:6]


def choose_integer_prefix(board, budget, observed, *, remaining_steps, salt, strict=False):
    """Audit a selected complete shield prefix against the actual P9 action."""
    baseline = choose_p8_action(board, budget, observed, remaining_steps=remaining_steps,
                                salt=salt, mode="conservative")
    if baseline.action is None:
        return (), {"accepted": False, "candidates": 0}
    plans = integer_candidates(board, budget, observed, remaining_steps)
    if not plans:
        return (), {"accepted": False, "candidates": 0}
    cache = {}

    def score(prefix, scenario):
        key = prefix, scenario
        if key not in cache:
            cache[key] = _rollout_prefix(board, budget, observed, prefix, remaining_steps,
                                          salt=salt, scenario=scenario)
        return cache[key]

    reference = (baseline.action,)
    # Select a single candidate on five scenarios, then audit without
    # reselection. Rejected prefixes leave the original P9 behavior intact.
    ranked = []
    for plan in plans:
        deltas = tuple(score(plan.shields, sample) - score(reference, sample) for sample in range(5))
        if sum(deltas) > 1e-9 and (not strict or min(deltas) >= -1e-9):
            ranked.append((-sum(deltas), tuple(a.target_node_1 for a in plan.shields), plan, deltas))
    if not ranked:
        return (), {"accepted": False, "candidates": len(plans), "rollouts": len(cache)}
    _, _, plan, selection = min(ranked)
    audit = tuple(score(plan.shields, sample) - score(reference, sample) for sample in range(5, 13))
    accepted = sum(audit) > 1e-9 and (not strict or min(audit) >= -1e-9)
    return (plan.shields if accepted else ()), {
        "accepted": accepted, "candidates": len(plans), "rollouts": len(cache),
        "proposed_shields": [a.target_node_1 for a in plan.shields],
        "selection_deltas": selection, "audit_deltas": audit,
        "search_predicted_score": plan.predicted_score,
        "solver_status": plan.solver_status,
    }

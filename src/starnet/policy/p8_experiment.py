"""P8 bounded public-state value-of-information rollout experiment.

The unobserved response assumption is explicitly ``r ~ Uniform(0.2, 1.5)``.
All counterfactual state stays in :class:`PredictiveState` and a dedicated
read-only projection; it is never written to the factual Blackboard.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import random
from types import MappingProxyType
from typing import Literal, Mapping, MutableMapping

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.baseline import _response, public_response
from starnet.policy.budget_experiment import budget_plan
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.cmg import PredictiveState, bounded_response_delta
from starnet.policy.fast_settlement_experiment import FastComponentSettlement
from starnet.policy.structural import ExperimentalPublicGreedyPlanner, public_positive_graph_gate_closed


P8Mode = Literal["expected", "conservative", "audited"]
EvaluationCache = MutableMapping[tuple[object, ...], float]
_FAST_SETTLEMENT = FastComponentSettlement(max_topologies=128)


@dataclass(frozen=True)
class _ProjectedNode:
    w: float
    persona: str
    comm_left: int | None


@dataclass(frozen=True)
class _ProjectedBoard:
    nodes: Mapping[int, _ProjectedNode]
    edges: frozenset[tuple[int, int]]
    dead_nodes: frozenset[int]
    node_count: int

    @classmethod
    def from_state(cls, state: PredictiveState, node_count: int) -> "_ProjectedBoard":
        nodes = MappingProxyType({
            node_id: _ProjectedNode(node.w, node.persona, node.comm_left)
            for node_id, node in state.nodes.items()
        })
        return cls(nodes, frozenset(state.edges), frozenset(state.dead_nodes), node_count)

    @property
    def scanned_ids(self) -> frozenset[int]:
        return frozenset(self.nodes) | self.dead_nodes

    @property
    def shielded_ids(self) -> frozenset[int]:
        return self.dead_nodes


@dataclass(frozen=True)
class P8Decision:
    action: Action | None
    baseline_action: Action | None
    source: str
    compared_actions: tuple[Action, ...]
    paired_deltas: tuple[float, ...]
    mean_delta: float
    minimum_delta: float
    rollouts: int
    proposed_action: Action | None = None
    audit_paired_deltas: tuple[float, ...] = ()
    audit_mean_delta: float = 0.0
    audit_minimum_delta: float = 0.0

    @property
    def deviated(self) -> bool:
        return self.action is not None and self.action != self.baseline_action


def _action_key(action: Action) -> tuple[object, ...]:
    return (action.kind, action.target_node_1, action.target_node_2, action.prompt_id)


def _public_state_payload(board: Blackboard | _ProjectedBoard) -> dict[str, object]:
    return {
        "node_count": board.node_count,
        "nodes": [[node_id, node.w, node.persona, node.comm_left]
                  for node_id, node in sorted(board.nodes.items())],
        "edges": [list(edge) for edge in sorted(board.edges)],
        "dead_nodes": sorted(board.dead_nodes),
    }


def public_board_salt(board: Blackboard) -> str:
    """Hash a complete initial public board without events or private data."""
    if board.node_count is None or len(board.scanned_ids) != board.node_count:
        raise ValueError("P8 salt requires a completely scanned public board")
    payload = json.dumps(_public_state_payload(board), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_digest(board: Blackboard | _ProjectedBoard) -> str:
    payload = json.dumps(_public_state_payload(board), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _response_fn(board: Blackboard | _ProjectedBoard, observed: Mapping[int, float]):
    estimate = _response if public_positive_graph_gate_closed(board) else public_response
    return lambda node_id, node, turn: estimate(
        node_id, node.persona, turn, observed, DEFAULT_CALIBRATION_PROFILE,
    )


def _greedy_candidates(board: Blackboard | _ProjectedBoard, budget: float,
                       observed: Mapping[int, float], *, fast: bool = True):
    planner = ExperimentalPublicGreedyPlanner(
        _response_fn(board, observed),
        candidate_limit=len(board.edges) + 2 * len(board.nodes) + 1,
        min_observed_responses=0,
        structure_roi_margin=1.0,
    )
    if fast:
        planner.predictor = _FAST_SETTLEMENT
    return planner.candidates(board, budget, observed_response_count=len(observed))


def _scenario_factor(salt: str, node_id: int, scenario: int) -> float:
    """Return mean plus six fixed antithetic Uniform(0.2, 1.5) pairs."""
    if scenario == 0:
        return 0.85
    if scenario not in range(1, 13):
        raise ValueError("P8 scenario must be in 0..12")
    pair = (scenario - 1) // 2
    digest = hashlib.sha256(f"{salt}:{node_id}:{pair}".encode("ascii")).digest()
    base = random.Random(int.from_bytes(digest[:8], "big")).uniform(0.2, 1.5)
    return base if scenario % 2 else 1.7 - base


def _rollout(
    board: Blackboard, budget: float, observed: Mapping[int, float], first_action: Action,
    remaining_steps: int, *, scenario: int, salt: str,
) -> float:
    if remaining_steps < 0 or not math.isfinite(budget) or budget < 0:
        raise ValueError("invalid P8 rollout resources")
    state = PredictiveState.from_blackboard(board)
    visible = dict(observed)
    pending: Action | None = first_action
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
            raise ValueError("illegal P8 rollout action")
        delta = None
        if action.kind == "comm":
            node = state.nodes[action.target_node_1]
            if node.comm_left is None:
                raise ValueError("missing public communication count")
            turn = 4 - node.comm_left
            first = visible.get(action.target_node_1)
            if first is None:
                nominal_first = 15.0 * _scenario_factor(salt, action.target_node_1, scenario)
                first = bounded_response_delta(node.w, nominal_first)
                # The simulated policy learns this response only now, after
                # the successful hypothetical action on its own path.
                visible[action.target_node_1] = first
            delta = bounded_response_delta(node.w, first * (0.5 ** (turn - 1)))
        state = state.apply(action, delta)
        budget -= action_cost(action)
    score = float(_FAST_SETTLEMENT.score(state))
    if not math.isfinite(score):
        raise ValueError("nonfinite P8 rollout score")
    return score


def _candidate_domain(
    board: Blackboard, budget: float, observed: Mapping[int, float], remaining_steps: int,
) -> tuple[tuple[Action, str], ...]:
    ranked = _greedy_candidates(board, budget, observed)
    if not ranked:
        return ()
    candidates: list[tuple[Action, str]] = [(ranked[0].action, "public_greedy")]
    plan = budget_plan(board, budget, _response_fn(board, observed),
                       remaining_steps=remaining_steps, depth=1, width=2)
    if plan.actions and plan.actions[0].kind in {"cut", "shield"}:
        candidates.append((plan.actions[0], "p7_budget_structure"))
    structures = [item for item in ranked if item.action.kind in {"cut", "shield"}]
    if structures:
        best = min(structures, key=lambda item: (-item.score, item.candidate_id))
        candidates.append((best.action, "immediate_structure_gain"))
    untried = [item for item in ranked if item.action.kind == "comm"
               and item.action.target_node_1 not in observed]
    if untried:
        best = min(untried, key=lambda item: (-item.roi, -item.score, item.candidate_id))
        candidates.append((best.action, "untried_comm_roi"))
    unique: list[tuple[Action, str]] = []
    seen: set[Action] = set()
    for action, source in candidates:
        if action not in seen:
            seen.add(action)
            unique.append((action, source))
    return tuple(unique[:4])


def choose_p8_action(
    board: Blackboard, budget: float, observed: Mapping[int, float], *,
    remaining_steps: int, salt: str, mode: P8Mode,
    evaluation_cache: EvaluationCache | None = None,
) -> P8Decision:
    """Run a fixed mean screen, then five paired scenarios for one winner.

    This sequential screen is a bounded decision rule, not an unbiased
    estimate or a confidence interval.
    """
    if mode not in ("expected", "conservative", "audited"):
        raise ValueError("unknown P8 mode")
    if remaining_steps < 0 or not math.isfinite(budget) or budget < 0 or len(salt) != 64:
        raise ValueError("invalid P8 decision inputs")
    if any(not math.isfinite(float(value)) for value in observed.values()):
        raise ValueError("nonfinite public response")
    if remaining_steps == 0:
        return P8Decision(None, None, "none", (), (), 0.0, 0.0, 0)
    domain = _candidate_domain(board, budget, observed, remaining_steps)
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
        key = (digest, float(budget), remaining_steps, observed_key, salt,
               _action_key(action), scenario)
        if key not in cache:
            cache[key] = _rollout(board, budget, observed, action, remaining_steps,
                                  scenario=scenario, salt=salt)
            rollouts += 1
        value = float(cache[key])
        if not math.isfinite(value):
            raise ValueError("nonfinite cached P8 score")
        return value

    baseline_mean = score(baseline, 0)
    screened_structures: list[tuple[float, tuple[object, ...], Action, str]] = []
    untried_comm: tuple[Action, str] | None = None
    for action, source in domain[1:]:
        delta = score(action, 0) - baseline_mean
        if source == "untried_comm_roi":
            # A constant mean response deliberately removes the value of
            # learning. Preserve this candidate for the heterogeneous paired
            # scenarios even when its mean-only screen is neutral.
            untried_comm = (action, source)
        elif action.kind in {"cut", "shield"} and delta > 1e-9:
            screened_structures.append((-delta, _action_key(action), action, source))
    finalists: list[tuple[Action, str]] = []
    if screened_structures:
        _, _, action, source = min(screened_structures)
        finalists.append((action, source))
    if untried_comm is not None and untried_comm[0] not in {item[0] for item in finalists}:
        finalists.append(untried_comm)
    if not finalists:
        return P8Decision(baseline, baseline, "public_greedy",
                          tuple(action for action, _ in domain), (), 0.0, 0.0, rollouts)
    accepted: list[tuple[float, tuple[object, ...], Action, str,
                         tuple[float, ...], float, float]] = []
    for candidate, source in finalists:
        deltas = tuple(score(candidate, scenario) - score(baseline, scenario)
                       for scenario in range(5))
        mean_delta = sum(deltas) / len(deltas)
        minimum = min(deltas)
        if mean_delta > 1e-9 and (mode == "expected" or minimum >= -1e-9):
            accepted.append((-mean_delta, _action_key(candidate), candidate, source,
                             deltas, mean_delta, minimum))
    if not accepted:
        return P8Decision(baseline, baseline, "public_greedy",
                          tuple(action for action, _ in domain), (), 0.0, 0.0, rollouts)
    _, _, winner, source, deltas, mean_delta, minimum = min(accepted)
    compared = tuple(action for action, _ in domain)
    if mode != "audited":
        return P8Decision(winner, baseline, source, compared, deltas,
                          mean_delta, minimum, rollouts, proposed_action=winner)
    audit_deltas = tuple(score(winner, scenario) - score(baseline, scenario)
                         for scenario in range(5, 13))
    audit_mean = sum(audit_deltas) / len(audit_deltas)
    audit_minimum = min(audit_deltas)
    audit_passed = audit_mean > 1e-9 and audit_minimum >= -1e-9
    return P8Decision(
        winner if audit_passed else baseline, baseline,
        source if audit_passed else "public_greedy", compared,
        deltas, mean_delta, minimum, rollouts, proposed_action=winner,
        audit_paired_deltas=audit_deltas, audit_mean_delta=audit_mean,
        audit_minimum_delta=audit_minimum,
    )


__all__ = ["EvaluationCache", "P8Decision", "P8Mode", "choose_p8_action", "public_board_salt"]

"""Offline-only budget-complete structural search on copied public state."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Any, Callable

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.cmg import PredictiveState
from starnet.policy.structural import public_structure_risk_allowed

ResponseFn = Callable[[int, Any, int], float]


@dataclass(frozen=True)
class BudgetPlan:
    score: float
    actions: tuple[Action, ...]


def communication_tail(
    state: PredictiveState, budget: float, response_fn: ResponseFn, remaining_steps: int,
) -> BudgetPlan:
    """Exact equal-cost allocation for nonnegative diminishing responses.

    Under the experimental degree-plus-one consensus model, a fixed
    topology's score is linear. A heap preserves each node's slot precedence.
    """
    adjacency = {node_id: set() for node_id in state.nodes}
    for left, right in state.edges:
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    coefficients: dict[int, float] = {}
    unseen = set(state.nodes)
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        component = [start]
        for node_id in component:
            for neighbor in sorted(adjacency[node_id]):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.append(neighbor)
        factor = len(component) / sum(len(adjacency[node_id]) + 1 for node_id in component)
        coefficients.update({node_id: factor * (len(adjacency[node_id]) + 1) for node_id in component})
    score = sum(coefficients[node_id] * node.w for node_id, node in state.nodes.items())
    heap: list[tuple[float, str, int, int]] = []
    gains: dict[tuple[int, int], float] = {}
    for node_id, node in sorted(state.nodes.items()):
        if not node.comm_left:
            continue
        previous = math.inf
        for turn in range(4 - node.comm_left, 4):
            delta = float(response_fn(node_id, node, turn))
            if not math.isfinite(delta) or delta < 0 or delta > previous + 1e-9:
                raise ValueError("response must be finite, nonnegative and diminishing")
            previous = delta
            gains[node_id, turn] = coefficients[node_id] * delta
        turn = 4 - node.comm_left
        heapq.heappush(heap, (-gains[node_id, turn], f"comm:{node_id}:{turn}", node_id, turn))
    actions: list[Action] = []
    for _ in range(min(max(0, int(budget // 2)), max(0, remaining_steps))):
        if not heap or heap[0][0] >= 0:
            break
        negative_gain, _, node_id, turn = heapq.heappop(heap)
        score -= negative_gain
        actions.append(Action("comm", node_id, prompt_id=1))
        if turn < 3:
            heapq.heappush(heap, (-gains[node_id, turn + 1], f"comm:{node_id}:{turn + 1}", node_id, turn + 1))
    return BudgetPlan(score, tuple(actions))


def budget_plan(
    board: Blackboard, budget: float, response_fn: ResponseFn, *,
    remaining_steps: int, depth: int = 2, width: int = 4,
) -> BudgetPlan:
    """Compare complete allocations, retaining the public structure gate.

    This module has no production configuration flag. Calibration and scenario
    promotion are required before a runtime may expose its plans to an LLM.
    """
    if depth < 0 or width <= 0 or remaining_steps < 0 or not math.isfinite(budget) or budget < 0:
        raise ValueError("invalid planning limits")
    initial = PredictiveState.from_blackboard(board)
    best = communication_tail(initial, budget, response_fn, remaining_steps)
    hypotheses = [Action("shield", node_id) for node_id in sorted(initial.nodes)]
    hypotheses += [Action("cut", left, target_node_2=right) for left, right in sorted(initial.edges)]
    # The gate sees only returned facts, never a Blackboard with predictions.
    hypotheses = [action for action in hypotheses if is_legal_action(action, board, budget)
                  and public_structure_risk_allowed(board, action, 1.0)]
    beam = [(initial, (), budget)]
    for _ in range(min(depth, remaining_steps)):
        ranked = []
        visited = set()
        for state, prefix, available in beam:
            for action in hypotheses:
                cost = action_cost(action)
                if cost > available or action.target_node_1 not in state.nodes:
                    continue
                if action.kind == "cut" and tuple(sorted((action.target_node_1, action.target_node_2))) not in state.edges:
                    continue
                changed = state.apply(action)
                key = (frozenset(changed.nodes), frozenset(changed.edges))
                # Equal topology with different costs must remain distinct.
                visit_key = (key, available - cost)
                if visit_key in visited:
                    continue
                visited.add(visit_key)
                sequence = prefix + (action,)
                tail = communication_tail(changed, available - cost, response_fn, remaining_steps - len(sequence))
                plan = BudgetPlan(tail.score, sequence + tail.actions)
                if plan.score > best.score + 1e-9:
                    best = plan
                ranked.append((plan.score, len(ranked), changed, sequence, available - cost))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        beam = [(row[2], row[3], row[4]) for row in ranked[:width]]
        if not beam:
            break
    return best

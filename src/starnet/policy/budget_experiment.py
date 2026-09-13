"""Offline-only budget-complete structural search on copied public state."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Any, Callable

import networkx as nx

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.cmg import PredictiveState, bounded_response_delta
from starnet.policy.structural import public_structure_risk_allowed

ResponseFn = Callable[[int, Any, int], float]


@dataclass(frozen=True)
class BudgetPlan:
    score: float
    actions: tuple[Action, ...]


def _realized_responses(
    state: PredictiveState,
    responses: dict[tuple[int, int], float],
) -> dict[tuple[int, int], float]:
    """Apply each node's slots cumulatively against its remaining opinion space."""
    realized: dict[tuple[int, int], float] = {}
    for node_id, node in state.nodes.items():
        if not node.comm_left:
            continue
        opinion = float(node.w)
        for turn in range(4 - node.comm_left, 4):
            delta = bounded_response_delta(opinion, responses[node_id, turn])
            realized[node_id, turn] = delta
            opinion += delta
    return realized


def _connected_structure_score(
    state: PredictiveState, action: Action, graph: nx.Graph,
    responses: dict[tuple[int, int], float], budget: float, steps: int,
) -> float:
    """Fast linear score when a certified non-bridge/non-articulation changes."""
    removed = action.target_node_1 if action.kind == "shield" else None
    affected = set(graph[removed]) if removed is not None else {action.target_node_1, action.target_node_2}
    degrees = {node_id: graph.degree[node_id] + 1 - int(node_id in affected)
               for node_id in state.nodes if node_id != removed}
    if not degrees:
        return 0.0
    factor = len(degrees) / sum(degrees.values())
    score = sum(factor * degree * state.nodes[node_id].w for node_id, degree in degrees.items())
    realized = _realized_responses(state, responses)
    gains = [factor * degree * realized[node_id, turn]
             for node_id, degree in degrees.items() if state.nodes[node_id].comm_left
             for turn in range(4 - state.nodes[node_id].comm_left, 4)]
    for gain in heapq.nlargest(min(int(budget // 2), steps), gains):
        if gain > 0:
            score += gain
    return score


def communication_tail(
    state: PredictiveState, budget: float, response_fn: ResponseFn, remaining_steps: int,
    *, include_actions: bool = True,
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
    nominal: dict[tuple[int, int], float] = {}
    for node_id, node in sorted(state.nodes.items()):
        if not node.comm_left:
            continue
        previous = math.inf
        for turn in range(4 - node.comm_left, 4):
            delta = float(response_fn(node_id, node, turn))
            if not math.isfinite(delta) or delta < 0 or delta > previous + 1e-9:
                raise ValueError("response must be finite, nonnegative and diminishing")
            previous = delta
            nominal[node_id, turn] = delta
    realized = _realized_responses(state, nominal)
    gains = {key: coefficients[key[0]] * delta for key, delta in realized.items()}
    for node_id, node in sorted(state.nodes.items()):
        if not node.comm_left:
            continue
        turn = 4 - node.comm_left
        heapq.heappush(heap, (-gains[node_id, turn], f"comm:{node_id}:{turn}", node_id, turn))
    slots = min(max(0, int(budget // 2)), max(0, remaining_steps))
    if not include_actions:
        for gain in heapq.nlargest(slots, gains.values()):
            if gain > 0:
                score += gain
        return BudgetPlan(score, ())
    actions: list[Action] = []
    for _ in range(slots):
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
    # Structure changes neither a survivor's opinion nor its response slots.
    responses = {(node_id, turn): response_fn(node_id, node, turn)
                 for node_id, node in initial.nodes.items() if node.comm_left
                 for turn in range(4 - node.comm_left, 4)}
    fixed_response = lambda node_id, _node, turn: responses[node_id, turn]
    best = communication_tail(initial, budget, fixed_response, remaining_steps)
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
            graph = nx.Graph()
            graph.add_nodes_from(state.nodes)
            graph.add_edges_from(state.edges)
            connected = bool(state.nodes) and nx.is_connected(graph)
            articulations = set(nx.articulation_points(graph)) if connected else set()
            bridges = {tuple(sorted(edge)) for edge in nx.bridges(graph)} if connected else set()
            for action in hypotheses:
                cost = action_cost(action)
                if cost > available or action.target_node_1 not in state.nodes:
                    continue
                if action.kind == "cut" and tuple(sorted((action.target_node_1, action.target_node_2))) not in state.edges:
                    continue
                # Canonical topology changes also collapse cuts subsequently
                # erased by a shield, just like a full copied-state key.
                sequence = prefix + (action,)
                removed = frozenset(item.target_node_1 for item in sequence if item.kind == "shield")
                cuts = frozenset(tuple(sorted((item.target_node_1, item.target_node_2)))
                                 for item in sequence if item.kind == "cut"
                                 and item.target_node_1 not in removed and item.target_node_2 not in removed)
                key = (removed, cuts)
                # Equal topology with different costs must remain distinct.
                visit_key = (key, available - cost)
                if visit_key in visited:
                    continue
                visited.add(visit_key)
                fast = connected and (
                    action.kind == "shield" and action.target_node_1 not in articulations
                    or action.kind == "cut" and tuple(sorted((action.target_node_1, action.target_node_2))) not in bridges
                )
                changed = None
                if fast:
                    score = _connected_structure_score(state, action, graph, responses, available - cost, remaining_steps - len(sequence))
                else:
                    changed = state.apply(action)
                    score = communication_tail(changed, available - cost, fixed_response, remaining_steps - len(sequence), include_actions=False).score
                if score > best.score + 1e-9:
                    changed = changed or state.apply(action)
                    selected = communication_tail(changed, available - cost, fixed_response, remaining_steps - len(sequence))
                    best = BudgetPlan(selected.score, sequence + selected.actions)
                ranked.append((score, len(ranked), state, sequence, available - cost))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        beam = [(row[2].apply(row[3][-1]), row[3], row[4]) for row in ranked[:width]]
        if not beam:
            break
    return best

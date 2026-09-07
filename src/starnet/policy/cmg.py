"""Pure response-aware conservative marginal-gain planning for V1."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Iterable

import networkx as nx

from starnet.model.blackboard import Blackboard, NodeState
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.graph_analysis import analyze_graph


class CMGPlanningError(RuntimeError):
    """A fail-closed prediction or time-budget failure."""


@dataclass
class ResponseLedger:
    """Online posterior keyed by ``persona × prompt × turn``.

    A node's own successful response sequence is preferred.  Until that exists,
    the posterior is pooled by the exact calibration key, then falls back to
    the frozen calibration prior.
    """

    successful_comm_count: dict[int, int] = field(default_factory=dict)
    observed_deltas: dict[int, list[float]] = field(default_factory=dict)
    first_delta: dict[int, float] = field(default_factory=dict)
    last_w: dict[int, float] = field(default_factory=dict)
    posterior_count: dict[str, int] = field(default_factory=dict)
    posterior_mean: dict[str, float] = field(default_factory=dict)
    posterior_m2: dict[str, float] = field(default_factory=dict)

    def record_success(
        self, node_id: int, before_w: float, new_w: float,
        *, persona: str | None = None, prompt_id: int = 1, turn: int | None = None,
    ) -> None:
        delta = float(new_w) - float(before_w)
        if not math.isfinite(delta):
            raise CMGPlanningError("nonfinite_response")
        values = self.observed_deltas.setdefault(node_id, [])
        values.append(delta)
        self.successful_comm_count[node_id] = len(values)
        self.first_delta.setdefault(node_id, delta)
        self.last_w[node_id] = float(new_w)
        if persona is not None and turn in (1, 2, 3):
            key = CalibrationProfile.response_key(persona, prompt_id, turn)
            count = self.posterior_count.get(key, 0) + 1
            old_mean = self.posterior_mean.get(key, 0.0)
            difference = delta - old_mean
            mean = old_mean + difference / count
            self.posterior_count[key] = count
            self.posterior_mean[key] = mean
            self.posterior_m2[key] = self.posterior_m2.get(key, 0.0) + difference * (delta - mean)

    def predicted_delta(
        self, node_id: int, persona: str, prompt_id: int, profile: CalibrationProfile,
        turn: int | None = None,
    ) -> tuple[float, float] | None:
        count = self.successful_comm_count.get(node_id, 0)
        if count == 0:
            return self.posterior_for(persona, prompt_id, turn or 1, profile)
        first = self.first_delta.get(node_id)
        if first is None:
            return None
        # The copied predictive state may include further hypothetical slots
        # beyond the real ledger.  Honour its actual slot number when given;
        # without one preserve the historical "next observed slot" API.
        target_turn = turn if turn in (1, 2, 3) else count + 1
        if target_turn == 2:
            return first * 0.5, 0.0
        if target_turn == 3:
            return first * 0.25, 0.0
        return None

    def posterior_for(
        self, persona: str, prompt_id: int, turn: int, profile: CalibrationProfile
    ) -> tuple[float, float] | None:
        """Return the observed group posterior, or the calibrated prior."""
        key = CalibrationProfile.response_key(persona, prompt_id, turn)
        count = self.posterior_count.get(key, 0)
        if count:
            mean = self.posterior_mean[key]
            variance = self.posterior_m2.get(key, 0.0) / max(1, count - 1)
            return mean, math.sqrt(max(0.0, variance))
        return profile.response_prior(persona, prompt_id, turn)


@dataclass(frozen=True)
class PredictiveState:
    """A copied public state used for hypothetical actions only."""

    nodes: dict[int, NodeState]
    edges: set[tuple[int, int]]
    dead_nodes: set[int]

    @classmethod
    def from_blackboard(cls, board: Blackboard) -> "PredictiveState":
        return cls(
            nodes={node_id: NodeState(node.w, node.persona, node.comm_left) for node_id, node in board.nodes.items()},
            edges=set(board.edges),
            dead_nodes=set(board.dead_nodes),
        )

    def to_blackboard(self) -> Blackboard:
        board = Blackboard()
        board.nodes = {node_id: NodeState(node.w, node.persona, node.comm_left) for node_id, node in self.nodes.items()}
        board.edges = set(self.edges)
        board.dead_nodes = set(self.dead_nodes)
        return board

    def apply(self, action: Action, comm_delta: float | None = None) -> "PredictiveState":
        # This method is called for every structural counterfactual.  Copy the
        # three public-state containers directly instead of constructing a
        # Blackboard, recording an event, and converting it back each time.
        # The resulting state is identical but avoids substantial allocator
        # and event-list churn on 100-node beam searches.
        nodes = {node_id: NodeState(node.w, node.persona, node.comm_left) for node_id, node in self.nodes.items()}
        edges = set(self.edges)
        dead_nodes = set(self.dead_nodes)
        if action.kind == "comm":
            if comm_delta is None or action.target_node_1 not in nodes:
                raise CMGPlanningError("invalid_hypothesis")
            nodes[action.target_node_1].w += comm_delta
            if nodes[action.target_node_1].comm_left is not None:
                nodes[action.target_node_1].comm_left = max(0, nodes[action.target_node_1].comm_left - 1)
        elif action.kind == "cut":
            if action.target_node_2 is None:
                raise CMGPlanningError("invalid_hypothesis")
            edges.discard(tuple(sorted((action.target_node_1, action.target_node_2))))
        elif action.kind == "shield":
            if action.target_node_1 not in nodes:
                raise CMGPlanningError("invalid_hypothesis")
            del nodes[action.target_node_1]
            dead_nodes.add(action.target_node_1)
            edges = {edge for edge in edges if action.target_node_1 not in edge}
        else:
            raise CMGPlanningError("invalid_hypothesis")
        return PredictiveState(nodes, edges, dead_nodes)


@dataclass(frozen=True)
class ScoredCandidate:
    candidate_id: str
    action: Action
    score_before: float
    score_after: float
    gain: float
    sigma: float
    lcb_roi: float
    response_delta: float | None = None


class SettlementPredictor:
    """The three preregistered offline settlement model families."""

    def __init__(self, profile: CalibrationProfile, *, iterations: int = 200, threshold: float = 1e-8) -> None:
        self.profile = profile
        self.iterations = iterations
        self.threshold = threshold

    def score(self, state: PredictiveState) -> float:
        nodes = sorted(state.nodes)
        if not nodes:
            return 0.0
        if self.profile.model == "component_degree_plus_one":
            # Keep the verified formula exactly, but avoid constructing a
            # NetworkX graph for every hypothetical state.  This is the hot
            # path in B4 and is materially cheaper and smaller on 100-node
            # graphs under the 4-GiB experiment limit.
            parent = {node: node for node in nodes}
            degree = {node: 0 for node in nodes}

            def find(node: int) -> int:
                root = node
                while parent[root] != root:
                    root = parent[root]
                while parent[node] != node:
                    next_node = parent[node]
                    parent[node] = root
                    node = next_node
                return root

            def union(left: int, right: int) -> None:
                left_root, right_root = find(left), find(right)
                if left_root != right_root:
                    parent[right_root] = left_root

            for left, right in state.edges:
                if left in degree and right in degree:
                    degree[left] += 1
                    degree[right] += 1
                    union(left, right)
            totals: dict[int, tuple[int, float, int]] = {}
            for node in nodes:
                root = find(node)
                factor = degree[node] + 1
                size, weighted, denominator = totals.get(root, (0, 0.0, 0))
                totals[root] = (size + 1, weighted + factor * float(state.nodes[node].w), denominator + factor)
            return sum(size * weighted / denominator for size, weighted, denominator in totals.values())
        graph = nx.Graph()
        graph.add_nodes_from(nodes)
        graph.add_edges_from(edge for edge in state.edges if edge[0] in state.nodes and edge[1] in state.nodes)
        weights = {node: float(state.nodes[node].w) for node in nodes}
        if not all(math.isfinite(value) for value in weights.values()):
            raise CMGPlanningError("nonfinite_state")
        if self.profile.model == "degree":
            return sum(max(1, graph.degree(node)) * weights[node] for node in nodes)
        transition = self._transition(graph, nodes)
        if self.profile.model == "degroot":
            settled = self._iterate(transition, weights)
        else:
            n_minus_one = max(1, len(nodes) - 1)
            retain = {node: min(1.0, max(0.0, self.profile.a + self.profile.b * graph.degree(node) / n_minus_one)) for node in nodes}
            settled = self._iterate(transition, weights, retain)
        return sum(max(1, graph.degree(node)) * settled[node] for node in nodes)

    def _transition(self, graph: nx.Graph, nodes: list[int]) -> dict[int, dict[int, float]]:
        result: dict[int, dict[int, float]] = {}
        for node in nodes:
            degree = graph.degree(node)
            row = {node: 1.0 + self.profile.rho * degree}
            for neighbor in graph.neighbors(node):
                row[neighbor] = max(1, graph.degree(neighbor)) ** self.profile.gamma
            total = sum(row.values())
            if not math.isfinite(total) or total <= 0:
                raise CMGPlanningError("invalid_transition")
            result[node] = {target: value / total for target, value in row.items()}
        return result

    def _iterate(
        self, transition: dict[int, dict[int, float]], initial: dict[int, float], retain: dict[int, float] | None = None
    ) -> dict[int, float]:
        current = dict(initial)
        for _ in range(self.iterations):
            following: dict[int, float] = {}
            for node, row in transition.items():
                mixed = sum(weight * current[target] for target, weight in row.items())
                following[node] = mixed if retain is None else retain[node] * initial[node] + (1.0 - retain[node]) * mixed
            if not all(math.isfinite(value) for value in following.values()):
                raise CMGPlanningError("nonfinite_prediction")
            if max(abs(following[node] - current[node]) for node in current) <= self.threshold:
                return following
            current = following
        raise CMGPlanningError("nonconvergent")


def _cmg_cut_candidates(board: Blackboard, limit: int) -> list[Action]:
    edges = sorted(board.edges)
    if len(edges) <= limit:
        return [Action("cut", left, target_node_2=right) for left, right in edges]
    analysis = analyze_graph(board)
    graph = analysis.graph
    scores: list[tuple[float, str, Action]] = []
    max_negative = max((max(0.0, -node.w) for node in board.nodes.values()), default=0.0) or 1.0
    max_influence = max((metrics.positive_influence for metrics in analysis.node_metrics.values()), default=0.0) or 1.0
    for left, right in edges:
        left_state, right_state = board.nodes[left], board.nodes[right]
        metrics = analysis.edge_metrics.get((left, right))
        betweenness = metrics.edge_betweenness if metrics else 0.0
        cross = 1.0 if metrics and metrics.cross_community else 0.0
        endpoint_influence = max(analysis.node_metrics[left].positive_influence, analysis.node_metrics[right].positive_influence)
        score = 0.5 * max(max(0.0, -left_state.w), max(0.0, -right_state.w)) / max_negative
        score += 0.25 * endpoint_influence / max_influence
        score += 0.25 * (betweenness + cross) / 2.0
        action = Action("cut", left, target_node_2=right)
        scores.append((-score, f"cut:{left}-{right}", action))
    return [item[2] for item in sorted(scores)[:limit]]


def enumerate_cmg_actions(board: Blackboard, budget: float, cut_limit: int) -> list[Action]:
    actions: list[Action] = []
    for node_id in sorted(board.nodes):
        actions.extend((Action("comm", node_id, prompt_id=1), Action("shield", node_id)))
    actions.extend(_cmg_cut_candidates(board, cut_limit))
    return [action for action in actions if is_legal_action(action, board, budget)]


def choose_cmg_action(
    board: Blackboard, ledger: ResponseLedger, profile: CalibrationProfile, budget: float,
    *, cut_limit: int = 64, iterations: int = 200, threshold: float = 1e-8, planning_seconds: float = 1.0,
) -> ScoredCandidate | None:
    if not profile.verified:
        raise CMGPlanningError("profile_unavailable")
    started = time.monotonic()
    state = PredictiveState.from_blackboard(board)
    predictor = SettlementPredictor(profile, iterations=iterations, threshold=threshold)
    before = predictor.score(state)
    scored: list[ScoredCandidate] = []
    for action in enumerate_cmg_actions(board, budget, cut_limit):
        if time.monotonic() - started > planning_seconds:
            raise CMGPlanningError("planning_timeout")
        delta: float | None = None
        response_sigma = 0.0
        if action.kind == "comm":
            node = board.nodes[action.target_node_1]
            response = ledger.predicted_delta(action.target_node_1, node.persona, 1, profile)
            if response is None:
                raise CMGPlanningError("missing_response_prior")
            delta, response_sigma = response
        after = predictor.score(state.apply(action, delta))
        residual = profile.residual_for(action.kind)
        response_score_sigma = 0.0
        if action.kind == "comm" and response_sigma > 0.0:
            assert delta is not None
            # Priors are measured in w units.  Transform their uncertainty
            # through the same settlement score before combining it with the
            # score-space calibration residual (important for high-degree nodes).
            score_high = predictor.score(state.apply(action, delta + response_sigma))
            score_low = predictor.score(state.apply(action, delta - response_sigma))
            response_score_sigma = max(abs(score_high - after), abs(after - score_low))
        sigma = math.hypot(residual, response_score_sigma)
        gain = after - before
        roi = (gain - sigma) / action_cost(action)
        if not all(math.isfinite(value) for value in (after, sigma, gain, roi)):
            raise CMGPlanningError("nonfinite_prediction")
        candidate_id = (
            f"comm:{action.target_node_1}:1" if action.kind == "comm" else
            f"shield:{action.target_node_1}" if action.kind == "shield" else
            f"cut:{action.target_node_1}-{action.target_node_2}"
        )
        scored.append(ScoredCandidate(candidate_id, action, before, after, gain, sigma, roi, delta))
    positives = [item for item in scored if item.lcb_roi > 0.0]
    return min(positives, key=lambda item: (-item.lcb_roi, item.candidate_id)) if positives else None

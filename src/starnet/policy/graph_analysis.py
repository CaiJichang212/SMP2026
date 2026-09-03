"""Deterministic NetworkX-derived graph metrics for the intervention policy.

The blackboard remains the source of truth. This module only creates a fresh
read model of its scanned, live nodes for scoring and candidate generation.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping, TypeVar

import networkx as nx

from starnet.model.blackboard import Blackboard, Edge, normalize_edge


MetricKey = TypeVar("MetricKey")


@dataclass(frozen=True)
class NodeMetrics:
    """Normalized structural and policy scores for one scanned live node."""

    degree: float
    pagerank: float
    core: float
    betweenness: float
    voterank: float
    influence: float
    positive_influence: float
    danger: float
    community_id: int


@dataclass(frozen=True)
class EdgeMetrics:
    """Normalized structural and negative-flow scores for one live edge."""

    edge_betweenness: float
    cross_community: bool
    negative_flow: float


@dataclass(frozen=True)
class GraphAnalysis:
    """Read-only metrics consumed by the candidate-generation policy.

    ``node_metrics`` is keyed by node ID and ``edge_metrics`` by normalized
    ``(min_node_id, max_node_id)`` edges. Candidate generation should consult
    the blackboard again before producing or executing an action.
    """

    graph: nx.Graph
    node_metrics: Mapping[int, NodeMetrics]
    edge_metrics: Mapping[Edge, EdgeMetrics]
    community_count: int

    @property
    def nodes(self) -> Mapping[int, NodeMetrics]:
        """Short alias for callers that only need node metrics."""
        return self.node_metrics

    @property
    def edges(self) -> Mapping[Edge, EdgeMetrics]:
        """Short alias for callers that only need edge metrics."""
        return self.edge_metrics

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()


def stable_normalize(values: Mapping[MetricKey, float]) -> dict[MetricKey, float]:
    """Min-max normalize scores without NaN, division-by-zero, or tie drift.

    An all-zero feature stays zero. A constant, non-zero feature is retained as
    one for every element so structurally equivalent positive signals are not
    accidentally erased.
    """
    if not values:
        return {}

    cleaned = {
        key: float(value) if math.isfinite(float(value)) else 0.0
        for key, value in values.items()
    }
    minimum = min(cleaned.values())
    maximum = max(cleaned.values())
    if minimum == maximum:
        constant = 0.0 if maximum == 0.0 else 1.0
        return {key: constant for key in values}

    span = maximum - minimum
    return {
        key: min(1.0, max(0.0, (cleaned[key] - minimum) / span))
        for key in values
    }


def build_graph(blackboard: Blackboard) -> nx.Graph:
    """Build a deterministic, derived graph from known live blackboard state."""
    graph = nx.Graph()
    live_nodes = sorted(blackboard.nodes)
    graph.add_nodes_from(live_nodes)

    live_node_set = set(live_nodes)
    for left, right in sorted(blackboard.edges):
        edge = normalize_edge(left, right)
        if edge[0] in live_node_set and edge[1] in live_node_set:
            graph.add_edge(*edge)
    return graph


def _deterministic_pagerank(graph: nx.Graph) -> dict[int, float]:
    """Run PageRank with a pure-Python fallback when NetworkX lacks numpy."""
    nodes = list(graph.nodes)
    if not nodes:
        return {}

    try:
        scores = nx.pagerank(graph, alpha=0.85, max_iter=1_000, tol=1.0e-12)
        return {node: float(scores[node]) for node in nodes}
    except (ImportError, ModuleNotFoundError, nx.PowerIterationFailedConvergence):
        pass

    # NetworkX's default implementation needs an optional numerical backend in
    # some supported versions. This is the same undirected random-walk update.
    node_count = len(nodes)
    alpha = 0.85
    scores = {node: 1.0 / node_count for node in nodes}
    for _ in range(1_000):
        dangling_mass = sum(scores[node] for node in nodes if graph.degree(node) == 0)
        updated: dict[int, float] = {}
        for node in nodes:
            inbound = sum(
                scores[neighbor] / graph.degree(neighbor)
                for neighbor in graph.neighbors(node)
            )
            updated[node] = (1.0 - alpha) / node_count + alpha * (
                inbound + dangling_mass / node_count
            )
        if sum(abs(updated[node] - scores[node]) for node in nodes) < 1.0e-12:
            return updated
        scores = updated
    return scores


def _communities(graph: nx.Graph) -> tuple[dict[int, int], int]:
    """Return stable community IDs, including isolated vertices."""
    if not graph.nodes:
        return {}, 0
    if graph.number_of_edges() == 0:
        groups = [{node} for node in graph.nodes]
    else:
        groups = [set(group) for group in nx.community.greedy_modularity_communities(graph)]

    groups.sort(key=lambda group: min(group))
    community_ids = {
        node: community_id
        for community_id, group in enumerate(groups)
        for node in sorted(group)
    }
    return community_ids, len(groups)


def _voterank_scores(graph: nx.Graph) -> dict[int, float]:
    """Convert NetworkX VoteRank's deterministic ordering to reciprocal ranks."""
    scores = {node: 0.0 for node in graph.nodes}
    for position, node in enumerate(nx.voterank(graph), start=1):
        scores[node] = 1.0 / position
    return scores


def _negative_strengths(blackboard: Blackboard, nodes: list[int]) -> dict[int, float]:
    raw = {node: max(-blackboard.nodes[node].w, 0.0) for node in nodes}
    maximum = max(raw.values(), default=0.0)
    if maximum == 0.0:
        return {node: 0.0 for node in nodes}
    return {node: raw[node] / maximum for node in nodes}


def _persona_prior(persona: str) -> float:
    return {"和平": 1.0, "中立": 0.7, "暴力": 0.0}.get(persona, 0.0)


def _persona_risk(persona: str) -> float:
    return {"暴力": 1.0, "中立": 0.5, "和平": 0.25}.get(persona, 0.5)


def _marginal_factor(comm_left: int) -> float:
    return {3: 1.0, 2: 0.5, 1: 0.25}.get(comm_left, 0.0)


def analyze_graph(blackboard: Blackboard) -> GraphAnalysis:
    """Compute deterministic structure, influence, danger, and edge metrics."""
    graph = build_graph(blackboard)
    nodes = list(graph.nodes)
    if not nodes:
        return GraphAnalysis(
            graph=graph,
            node_metrics=MappingProxyType({}),
            edge_metrics=MappingProxyType({}),
            community_count=0,
        )

    degree = stable_normalize(nx.degree_centrality(graph))
    pagerank = stable_normalize(_deterministic_pagerank(graph))
    core = stable_normalize(nx.core_number(graph))
    betweenness = stable_normalize(nx.betweenness_centrality(graph, normalized=True))
    # Reciprocal VoteRank is already in [0, 1]; applying min-max normalization
    # would destroy the specified 1 / rank semantics.
    voterank = _voterank_scores(graph)
    community_ids, community_count = _communities(graph)
    negative_strength = _negative_strengths(blackboard, nodes)

    node_metrics: dict[int, NodeMetrics] = {}
    for node in nodes:
        state = blackboard.nodes[node]
        influence = (
            0.25 * degree[node]
            + 0.25 * pagerank[node]
            + 0.20 * core[node]
            + 0.20 * betweenness[node]
            + 0.10 * voterank[node]
        )
        positive_influence = influence * _persona_prior(state.persona) * _marginal_factor(state.comm_left)
        danger = negative_strength[node] * _persona_risk(state.persona) * (
            0.70 * influence + 0.30 * betweenness[node]
        )
        node_metrics[node] = NodeMetrics(
            degree=degree[node],
            pagerank=pagerank[node],
            core=core[node],
            betweenness=betweenness[node],
            voterank=voterank[node],
            influence=min(1.0, max(0.0, influence)),
            positive_influence=min(1.0, max(0.0, positive_influence)),
            danger=min(1.0, max(0.0, danger)),
            community_id=community_ids[node],
        )

    raw_edge_betweenness = {
        normalize_edge(left, right): score
        for (left, right), score in nx.edge_betweenness_centrality(graph, normalized=True).items()
    }
    edge_betweenness = stable_normalize(raw_edge_betweenness)
    edge_metrics: dict[Edge, EdgeMetrics] = {}
    for edge in sorted(graph.edges):
        left, right = normalize_edge(*edge)
        left_metrics = node_metrics[left]
        right_metrics = node_metrics[right]
        negative_flow = max(
            left_metrics.danger * (1.0 - negative_strength[right]),
            right_metrics.danger * (1.0 - negative_strength[left]),
        )
        edge_metrics[(left, right)] = EdgeMetrics(
            edge_betweenness=edge_betweenness[(left, right)],
            cross_community=left_metrics.community_id != right_metrics.community_id,
            negative_flow=min(1.0, max(0.0, negative_flow)),
        )

    return GraphAnalysis(
        graph=graph,
        node_metrics=MappingProxyType(node_metrics),
        edge_metrics=MappingProxyType(edge_metrics),
        community_count=community_count,
    )


__all__ = [
    "EdgeMetrics",
    "GraphAnalysis",
    "NodeMetrics",
    "analyze_graph",
    "build_graph",
    "stable_normalize",
]

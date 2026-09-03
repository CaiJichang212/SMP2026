from __future__ import annotations

# Begin inline: src/starnet/model/blackboard.py
"""仅保存环境已公开信息的本地黑板。"""


from dataclasses import asdict, dataclass
from typing import Any


Edge = tuple[int, int]


def normalize_edge(left: int, right: int) -> Edge:
    """返回无向边的规范表示；自环不是任务中的有效通信链路。"""
    if left == right:
        raise ValueError("星网边不能连接节点自身")
    return (left, right) if left < right else (right, left)


@dataclass
class NodeState:
    """由一次成功扫描或成功游说得到的节点公开状态。"""

    w: float
    persona: str
    comm_left: int

    @classmethod
    def from_scan(cls, payload: dict[str, Any]) -> "NodeState":
        required = {"w", "persona", "comm_left", "neighbors"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"扫描结果缺少字段: {sorted(missing)}")
        return cls(
            w=float(payload["w"]),
            persona=str(payload["persona"]),
            comm_left=max(0, int(payload["comm_left"])),
        )


class Blackboard:
    """已探明存活节点、有效已知边与不可扫描节点的唯一事实来源。"""

    def __init__(self) -> None:
        self.nodes: dict[int, NodeState] = {}
        self.edges: set[Edge] = set()
        self.dead_nodes: set[int] = set()

    def can_scan(self, node_id: int) -> bool:
        return node_id > 0 and node_id not in self.nodes and node_id not in self.dead_nodes

    def record_scan(self, node_id: int, payload: dict[str, Any] | None) -> bool:
        """写入真实扫描结果；空结果只表示该 ID 当前不可用。"""
        if not self.can_scan(node_id):
            return False
        if payload is None:
            self.dead_nodes.add(node_id)
            return True

        state = NodeState.from_scan(payload)
        self.nodes[node_id] = state
        for neighbor in payload["neighbors"]:
            neighbor_id = int(neighbor)
            if neighbor_id > 0 and neighbor_id != node_id:
                self.edges.add(normalize_edge(node_id, neighbor_id))
        return True

    def record_communication(self, node_id: int, response: dict[str, Any]) -> bool:
        """仅在环境报告 success 时更新倾向和可沟通次数。"""
        node = self.nodes.get(node_id)
        if node is None or response.get("status") != "success":
            if node is not None and response.get("status") == "max_comm_reached":
                node.comm_left = 0
            return False
        if "new_w" not in response:
            return False
        node.w = float(response["new_w"])
        node.comm_left = max(0, node.comm_left - 1)
        return True

    def record_cut(self, left: int, right: int, success: bool) -> bool:
        if not success:
            return False
        self.edges.discard(normalize_edge(left, right))
        return True

    def record_shield(self, node_id: int, success: bool) -> bool:
        if not success or node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        self.edges = {edge for edge in self.edges if node_id not in edge}
        self.dead_nodes.add(node_id)
        return True

    def snapshot(self) -> dict[str, Any]:
        """为 LLM、日志与回归测试返回可 JSON 序列化的状态快照。"""
        return {
            "nodes": {node_id: asdict(state) for node_id, state in sorted(self.nodes.items())},
            "edges": [list(edge) for edge in sorted(self.edges)],
            "dead_nodes": sorted(self.dead_nodes),
        }

# End inline: src/starnet/model/blackboard.py

# Begin inline: src/starnet/policy/actions.py
"""动作预算与合法性校验，不依赖 LLM 或真实环境。"""


from dataclasses import dataclass
from typing import Literal



ActionKind = Literal["scan", "comm", "cut", "shield"]
ACTION_COST: dict[ActionKind, float] = {
    "scan": 0.5,
    "comm": 2.0,
    "cut": 3.0,
    "shield": 5.0,
}
VALID_PROMPT_IDS = frozenset({1, 2, 3})


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target_node_1: int
    target_node_2: int | None = None
    prompt_id: int | None = None


def action_cost(action: Action) -> float:
    return ACTION_COST[action.kind]


def is_legal_action(action: Action, blackboard: Blackboard, budget: float) -> bool:
    """在请求环境前拦截预算不足、未知边和重复动作。"""
    if budget < action_cost(action):
        return False

    node_id = action.target_node_1
    if action.kind == "scan":
        return action.target_node_2 is None and action.prompt_id is None and blackboard.can_scan(node_id)
    if action.kind == "comm":
        node = blackboard.nodes.get(node_id)
        return (
            action.target_node_2 is None
            and node is not None
            and node.comm_left > 0
            and action.prompt_id in VALID_PROMPT_IDS
        )
    if action.kind == "cut":
        if action.target_node_2 is None or action.prompt_id is not None:
            return False
        return normalize_edge(node_id, action.target_node_2) in blackboard.edges
    if action.kind == "shield":
        return action.target_node_2 is None and action.prompt_id is None and node_id in blackboard.nodes
    return False

# End inline: src/starnet/policy/actions.py

# Begin inline: src/starnet/runtime/env_adapter.py
"""环境调用的单一入口：只使用赛题公开 API，并以返回值更新黑板。"""


from typing import Any, Protocol



class StarNetEnvironment(Protocol):
    def scan_node(self, node_id: int) -> dict[str, Any] | None: ...
    def communicate(self, node_id: int, prompt_id: int) -> dict[str, Any]: ...
    def cut_link(self, left: int, right: int) -> bool: ...
    def shield_node(self, node_id: int) -> bool: ...


def apply_action(
    env: StarNetEnvironment, blackboard: Blackboard, action: Action, budget: float
) -> bool:
    """执行已校验动作；失败路径不虚构状态，也不访问环境私有成员。"""
    if not is_legal_action(action, blackboard, budget):
        return False

    if action.kind == "scan":
        return blackboard.record_scan(action.target_node_1, env.scan_node(action.target_node_1))
    if action.kind == "comm":
        assert action.prompt_id is not None
        response = env.communicate(action.target_node_1, action.prompt_id)
        return blackboard.record_communication(action.target_node_1, response)
    if action.kind == "cut":
        assert action.target_node_2 is not None
        success = env.cut_link(action.target_node_1, action.target_node_2)
        return blackboard.record_cut(action.target_node_1, action.target_node_2, success)
    if action.kind == "shield":
        return blackboard.record_shield(action.target_node_1, env.shield_node(action.target_node_1))
    return False

# End inline: src/starnet/runtime/env_adapter.py

# Begin inline: src/starnet/policy/graph_analysis.py
"""Deterministic NetworkX-derived graph metrics for the intervention policy.

The blackboard remains the source of truth. This module only creates a fresh
read model of its scanned, live nodes for scoring and candidate generation.
"""


from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping, TypeVar

import networkx as nx



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

# End inline: src/starnet/policy/graph_analysis.py

# Begin inline: src/starnet/policy/candidates.py
"""候选生成与不依赖 LLM 的批次选择。"""


import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any



MAX_PRIORITY_CANDIDATES: dict[int, int] = {0: 4, 1: 4, 2: 8}
MAX_CANDIDATES = 12
MAX_BATCH_SIZE = 10
VALID_BATCH_MODES = frozenset({"risk_first", "growth_first", "balanced"})


@dataclass(frozen=True)
class Candidate:
    """一个已经由 Python 验证过的环境动作。"""

    candidate_id: str
    action: Action
    priority: int
    score: float
    roi: float
    reason: str


def _candidate_sort_key(candidate: Candidate) -> tuple[int, float, float, str]:
    """计划规定的稳定候选排序。"""
    return (
        candidate.priority,
        -_finite_nonnegative(candidate.roi),
        action_cost(candidate.action),
        candidate.candidate_id,
    )


def _finite_nonnegative(value: float) -> float:
    return value if math.isfinite(value) and value >= 0.0 else 0.0


def _is_failed(candidate_id: str, action: Action, failed_actions: Iterable[object]) -> bool:
    """接受控制器按候选 ID 或 Action 记录的失败集合。"""
    return candidate_id in failed_actions or action in failed_actions


def _eligible(
    candidate_id: str,
    action: Action,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object],
) -> bool:
    return not _is_failed(candidate_id, action, failed_actions) and is_legal_action(
        action, blackboard, budget
    )


def _node_metric(analysis: GraphAnalysis, node_id: int) -> NodeMetrics | None:
    return analysis.node_metrics.get(node_id)


def _shield_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for node_id, node in sorted(blackboard.nodes.items()):
        metrics = _node_metric(analysis, node_id)
        if metrics is None or node.persona != "暴力" or node.w >= 0.0:
            continue
        danger = _finite_nonnegative(metrics.danger)
        if danger < 0.55:
            continue
        action = Action("shield", node_id)
        candidate_id = f"shield:{node_id}"
        if not _eligible(candidate_id, action, blackboard, budget, failed_actions):
            continue
        candidates.append(
            Candidate(
                candidate_id=candidate_id,
                action=action,
                priority=0,
                score=danger,
                roi=danger / action_cost(action),
                reason=f"high-risk violent node (danger={danger:.3f})",
            )
        )
    return sorted(candidates, key=_candidate_sort_key)[:MAX_PRIORITY_CANDIDATES[0]]


def _is_negative_bridge(
    left: NodeState,
    right: NodeState,
    left_metrics: NodeMetrics,
    right_metrics: NodeMetrics,
    edge_metrics: EdgeMetrics,
) -> bool:
    """返回是否存在从高风险端流向非暴力或非负端的传播风险。"""
    if not edge_metrics.cross_community:
        return False

    left_danger = _finite_nonnegative(left_metrics.danger)
    right_danger = _finite_nonnegative(right_metrics.danger)
    return (
        left_danger > 0.0 and (right.persona != "暴力" or right.w >= 0.0)
    ) or (
        right_danger > 0.0 and (left.persona != "暴力" or left.w >= 0.0)
    )


def _cut_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for edge, edge_metrics in sorted(analysis.edge_metrics.items()):
        left_id, right_id = normalize_edge(*edge)
        normalized_edge: Edge = (left_id, right_id)
        left = blackboard.nodes.get(left_id)
        right = blackboard.nodes.get(right_id)
        left_metrics = _node_metric(analysis, left_id)
        right_metrics = _node_metric(analysis, right_id)
        if (
            left is None
            or right is None
            or left_metrics is None
            or right_metrics is None
            or normalized_edge not in blackboard.edges
            or not _is_negative_bridge(left, right, left_metrics, right_metrics, edge_metrics)
        ):
            continue

        cut_score = _finite_nonnegative(edge_metrics.negative_flow) * _finite_nonnegative(
            edge_metrics.edge_betweenness
        )
        if cut_score < 0.20:
            continue
        action = Action("cut", left_id, target_node_2=right_id)
        candidate_id = f"cut:{left_id}-{right_id}"
        if not _eligible(candidate_id, action, blackboard, budget, failed_actions):
            continue
        candidates.append(
            Candidate(
                candidate_id=candidate_id,
                action=action,
                priority=1,
                score=cut_score,
                roi=cut_score / action_cost(action),
                reason=f"cross-community negative bridge (score={cut_score:.3f})",
            )
        )
    return sorted(candidates, key=_candidate_sort_key)[:MAX_PRIORITY_CANDIDATES[1]]


def _communicate_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for node_id, node in sorted(blackboard.nodes.items()):
        metrics = _node_metric(analysis, node_id)
        if metrics is None or node.persona not in {"和平", "中立"}:
            continue
        positive = _finite_nonnegative(metrics.positive_influence)
        if positive <= 0.0:
            continue
        action = Action("comm", node_id, prompt_id=1)
        candidate_id = f"comm:{node_id}:1"
        if not _eligible(candidate_id, action, blackboard, budget, failed_actions):
            continue
        candidates.append(
            Candidate(
                candidate_id=candidate_id,
                action=action,
                priority=2,
                score=positive,
                roi=positive / action_cost(action),
                reason=f"positive influence target (score={positive:.3f})",
            )
        )
    return sorted(candidates, key=_candidate_sort_key)[:MAX_PRIORITY_CANDIDATES[2]]


def generate_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object] = (),
) -> list[Candidate]:
    """从当前黑板和图指标生成稳定、已校验的候选集。

    P0 出现时，本轮只暴露 P0。拓扑或节点状态改变后的下一轮会重新生成 P1/P2，
    因此高危屏蔽不会被普通增益动作延后。
    """
    failed = frozenset(failed_actions)
    shields = _shield_candidates(analysis, blackboard, budget, failed)
    if shields:
        return shields[:MAX_CANDIDATES]

    cuts = _cut_candidates(analysis, blackboard, budget, failed)
    communications = _communicate_candidates(analysis, blackboard, budget, failed)
    return (cuts + communications)[:MAX_CANDIDATES]


def _conflicts(action: Action, selected_actions: Iterable[Action]) -> bool:
    """shield 与连接该节点的 cut 不能出现在同一批次。"""
    for selected in selected_actions:
        shield, cut = (action, selected) if action.kind == "shield" else (selected, action)
        if (
            shield.kind == "shield"
            and cut.kind == "cut"
            and shield.target_node_1 in {cut.target_node_1, cut.target_node_2}
        ):
            return True
    return False


def _valid_batch_ids(
    candidate_ids: Iterable[object],
    candidate_map: Mapping[str, Candidate],
    budget: float,
    limit: int,
) -> list[str]:
    """按给定顺序保留候选存在、非重复、无冲突且预算充足的前缀。"""
    selected_ids: list[str] = []
    selected_actions: list[Action] = []
    remaining_budget = max(0.0, float(budget))
    for candidate_id in candidate_ids:
        if not isinstance(candidate_id, str) or candidate_id in selected_ids:
            continue
        candidate = candidate_map.get(candidate_id)
        if candidate is None or len(selected_ids) >= limit:
            continue
        cost = action_cost(candidate.action)
        if cost > remaining_budget or _conflicts(candidate.action, selected_actions):
            continue
        selected_ids.append(candidate_id)
        selected_actions.append(candidate.action)
        remaining_budget -= cost
    return selected_ids


def select_deterministic_batch(
    candidates: Iterable[Candidate], budget: float, limit: int = MAX_BATCH_SIZE
) -> list[str]:
    """规则回退：按稳定优先级取预算内、互不冲突的动作。"""
    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    ordered = sorted(candidate_map.values(), key=_candidate_sort_key)
    return _valid_batch_ids(
        (candidate.candidate_id for candidate in ordered),
        candidate_map,
        budget,
        min(max(0, limit), MAX_BATCH_SIZE),
    )


def parse_llm_batch(
    payload: str | bytes | Mapping[str, Any] | None,
    candidate_map: Mapping[str, Candidate],
    budget: float,
) -> list[str]:
    """解析 Commander 的 JSON；任意无效或空结果均回退到确定性批次。"""
    fallback = select_deterministic_batch(candidate_map.values(), budget)
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return fallback
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return fallback
    if not isinstance(payload, Mapping):
        return fallback

    mode = payload.get("mode")
    candidate_ids = payload.get("candidate_ids")
    if mode not in VALID_BATCH_MODES or not isinstance(candidate_ids, list) or not candidate_ids:
        return fallback

    selected = _valid_batch_ids(candidate_ids, candidate_map, budget, MAX_BATCH_SIZE)
    return selected or fallback


__all__ = [
    "Candidate",
    "MAX_BATCH_SIZE",
    "MAX_CANDIDATES",
    "VALID_BATCH_MODES",
    "generate_candidates",
    "parse_llm_batch",
    "select_deterministic_batch",
]

# End inline: src/starnet/policy/candidates.py

# Begin inline: src/starnet/runtime/controller.py
"""确定性扫描、图分析和批次执行的纯 Python 运行时控制器。

这个模块不依赖 ``agent_mesa``。提交入口可以把 CaseVO 的 Commander 链包装成
``llm_ranker`` 回调，再把 ``RuntimeController.step()`` 的返回值直接作为模型
``step()`` 的状态码使用。
"""


from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence



MAX_LLM_CALLS = 3
MAX_BATCH_ACTIONS = 10
MAX_CONSECUTIVE_INVALID = 3


class ControllerState(str, Enum):
    """控制器的显式状态，便于模拟环境和提交入口观测。"""

    INIT = "INIT"
    SCAN_ALL = "SCAN_ALL"
    ANALYZE = "ANALYZE"
    PLAN_BATCH = "PLAN_BATCH"
    EXECUTE = "EXECUTE"
    REANALYZE = "REANALYZE"
    STOP = "STOP"


def infer_node_count(initial_budget: float) -> int:
    """从公开初始预算推断当前赛制规模。"""
    return 100 if initial_budget >= 150.0 else 50


class DeterministicScout:
    """按固定 ID 顺序扫描，完全不调用 LLM。"""

    def __init__(self, node_count: int) -> None:
        if node_count <= 0:
            raise ValueError("node_count 必须为正整数")
        self.node_count = node_count
        self._next_node_id = 1

    @property
    def exhausted(self) -> bool:
        return self._next_node_id > self.node_count

    def next_action(self, blackboard: Blackboard) -> Action | None:
        """返回下一个未知 ID 的 scan 动作；已知 ID 不会重复请求环境。"""
        while self._next_node_id <= self.node_count:
            node_id = self._next_node_id
            self._next_node_id += 1
            if blackboard.can_scan(node_id):
                return Action("scan", node_id)
        return None


class GraphAnalyst:
    """图分析模块的轻量角色包装，保留单文件提交时的清晰职责边界。"""

    def analyze(self, blackboard: Blackboard) -> GraphAnalysis:
        return analyze_graph(blackboard)

    def generate_candidates(
        self,
        analysis: GraphAnalysis,
        blackboard: Blackboard,
        budget: float,
        failed_actions: set[str],
    ) -> list[Candidate]:
        return generate_candidates(analysis, blackboard, budget, failed_actions)


LlmRanker = Callable[[dict[str, Any]], object]


@dataclass(frozen=True)
class BatchPlan:
    """一次仲裁后的候选 ID 队列及其来源。"""

    candidate_ids: tuple[str, ...]
    used_llm: bool


class BatchCommander:
    """负责 LLM 候选排序、调用配额和确定性回退。"""

    def __init__(self, llm_ranker: LlmRanker | None = None) -> None:
        self.llm_ranker = llm_ranker
        self.llm_calls = 0

    def plan(
        self,
        *,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
    ) -> BatchPlan:
        """返回 LLM 排序或确定性排序，LLM 故障不会传播到评测循环。"""
        candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
        selected_ids: list[str] = []
        used_llm = False

        if self.llm_ranker is not None and self.llm_calls < MAX_LLM_CALLS and candidate_map:
            # 计数在请求前递增，因此超时和异常也会消耗本次额度。
            self.llm_calls += 1
            try:
                payload = self._build_payload(candidates, budget, analysis)
                parsed = parse_llm_batch(self.llm_ranker(payload), candidate_map, budget)
                selected_ids = list(parsed or [])
                used_llm = bool(selected_ids)
            except Exception:
                selected_ids = []

        if not selected_ids:
            selected_ids = list(select_deterministic_batch(candidates, budget, MAX_BATCH_ACTIONS))

        return BatchPlan(tuple(selected_ids), used_llm)

    def _build_payload(
        self,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
    ) -> dict[str, Any]:
        graph = analysis.graph
        negative_nodes = sorted(
            node_id
            for node_id, metrics in analysis.node_metrics.items()
            if metrics.danger > 0
        )
        positive_nodes = sorted(
            node_id
            for node_id, metrics in analysis.node_metrics.items()
            if metrics.positive_influence > 0
        )
        return {
            "stage": ControllerState.PLAN_BATCH.value,
            "budget": budget,
            "llm_calls": self.llm_calls,
            "graph": {
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(),
                "community_count": analysis.community_count,
                "negative_nodes": negative_nodes,
                "positive_nodes": positive_nodes,
            },
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "action": asdict(candidate.action),
                    "cost": action_cost(candidate.action),
                    "priority": candidate.priority,
                    "roi": candidate.roi,
                    "reason": candidate.reason,
                }
                for candidate in candidates
            ],
        }


class RuntimeController:
    """每次 ``step`` 最多执行一次公开环境调用的 V0 状态机。

    ``step`` 返回 ``0`` 表示应继续调度，返回 ``1`` 表示停止。调用方若维护
    ``schedule.time``，仅应在 ``last_action_attempted`` 为真时递增一次。
    """

    def __init__(
        self,
        env: StarNetEnvironment,
        llm_ranker: LlmRanker | None = None,
        *,
        initial_budget: float | None = None,
        node_count: int | None = None,
        blackboard: Blackboard | None = None,
    ) -> None:
        self.env = env
        self.blackboard = blackboard if blackboard is not None else Blackboard()
        self.initial_budget = float(
            env.get_remaining_budget() if initial_budget is None else initial_budget
        )
        self.node_count = infer_node_count(self.initial_budget) if node_count is None else node_count
        self.scout = DeterministicScout(self.node_count)
        self.analyst = GraphAnalyst()
        self.commander = BatchCommander(llm_ranker)
        self.state = ControllerState.INIT
        self.analysis: GraphAnalysis | None = None
        self.candidates: dict[str, Candidate] = {}
        self.queue: list[str] = []
        self.failed_actions: set[str] = set()
        self.consecutive_invalid = 0
        self.last_action_attempted = False
        self.last_action_succeeded: bool | None = None

    @property
    def llm_calls(self) -> int:
        return self.commander.llm_calls

    @property
    def stopped(self) -> bool:
        return self.state is ControllerState.STOP

    def step(self) -> int:
        """推进状态机；本方法中任一路径至多调用一次环境 API。"""
        self.last_action_attempted = False
        self.last_action_succeeded = None

        # 状态转换不触发环境动作，可在同一个调度回合内继续直到需要执行动作。
        for _ in range(8):
            if self.state is ControllerState.STOP:
                return 1

            budget = float(self.env.get_remaining_budget())
            if self.state is ControllerState.INIT:
                self.state = ControllerState.SCAN_ALL
                continue

            if self.state is ControllerState.SCAN_ALL:
                return self._scan_next(budget)

            if self.state is ControllerState.ANALYZE:
                self._refresh_candidates(budget)
                self.state = ControllerState.PLAN_BATCH if self.candidates else ControllerState.STOP
                continue

            if self.state is ControllerState.PLAN_BATCH:
                if self.analysis is None or not self.candidates:
                    self.state = ControllerState.STOP
                    continue
                plan = self.commander.plan(
                    candidates=list(self.candidates.values()),
                    budget=budget,
                    analysis=self.analysis,
                )
                self.queue = self._valid_queue(plan.candidate_ids, budget)
                self.state = ControllerState.EXECUTE if self.queue else ControllerState.STOP
                continue

            if self.state is ControllerState.EXECUTE:
                return self._execute_next(budget)

            if self.state is ControllerState.REANALYZE:
                self._refresh_candidates(budget)
                previous_queue = self.queue
                self.queue = self._valid_queue(previous_queue, budget)
                invalidated = len(previous_queue) - len(self.queue)
                if invalidated:
                    self.consecutive_invalid += invalidated
                # 状态变化使过半队列失效时，旧批次已不再代表当前图，重新仲裁。
                if previous_queue and invalidated * 2 > len(previous_queue):
                    self.queue.clear()
                if self.consecutive_invalid >= MAX_CONSECUTIVE_INVALID:
                    self.queue.clear()
                    self.consecutive_invalid = 0
                if self.queue:
                    self.state = ControllerState.EXECUTE
                elif self.candidates:
                    self.state = ControllerState.PLAN_BATCH
                else:
                    self.state = ControllerState.STOP
                continue

        # 防止未来状态变更产生无界的无动作循环。
        self.state = ControllerState.STOP
        return 1

    def _scan_next(self, budget: float) -> int:
        action = self.scout.next_action(self.blackboard)
        if action is None:
            self.state = ControllerState.ANALYZE
            return 0
        if not is_legal_action(action, self.blackboard, budget):
            # 预算不足时，剩余扫描不能凭空完成。
            self.state = ControllerState.STOP
            return 1

        self.last_action_attempted = True
        try:
            self.last_action_succeeded = apply_action(self.env, self.blackboard, action, budget)
        except Exception:
            self.last_action_succeeded = False
        if self.scout.exhausted:
            self.state = ControllerState.ANALYZE
        return 0

    def _execute_next(self, budget: float) -> int:
        if not self.queue:
            self.state = ControllerState.REANALYZE
            return 0

        candidate_id = self.queue.pop(0)
        candidate = self.candidates.get(candidate_id)
        if candidate is None or candidate_id in self.failed_actions:
            self.consecutive_invalid += 1
            self.state = ControllerState.REANALYZE
            return 0
        if not is_legal_action(candidate.action, self.blackboard, budget):
            self.consecutive_invalid += 1
            self.state = ControllerState.REANALYZE
            return 0

        self.last_action_attempted = True
        try:
            success = apply_action(self.env, self.blackboard, candidate.action, budget)
        except Exception:
            success = False
        self.last_action_succeeded = success
        if success:
            self.consecutive_invalid = 0
        else:
            self.failed_actions.add(candidate_id)
            self.consecutive_invalid += 1
        self.state = ControllerState.REANALYZE
        return 0

    def _refresh_candidates(self, budget: float) -> None:
        self.analysis = self.analyst.analyze(self.blackboard)
        candidates = self.analyst.generate_candidates(
            self.analysis,
            self.blackboard,
            budget,
            self.failed_actions,
        )
        self.candidates = {candidate.candidate_id: candidate for candidate in candidates}

    def _valid_queue(self, candidate_ids: Sequence[str], budget: float) -> list[str]:
        """再次校验 LLM/旧队列，过滤未知、失效、冲突和超预算动作。"""
        accepted: list[str] = []
        seen: set[str] = set()
        shielded_nodes: set[int] = set()
        cut_endpoints: set[int] = set()
        remaining = budget
        for candidate_id in candidate_ids:
            if len(accepted) >= MAX_BATCH_ACTIONS or candidate_id in seen:
                continue
            seen.add(candidate_id)
            candidate = self.candidates.get(candidate_id)
            if candidate is None or candidate_id in self.failed_actions:
                continue
            action = candidate.action
            cost = action_cost(action)
            if cost > remaining or not is_legal_action(action, self.blackboard, remaining):
                continue
            if action.kind == "shield":
                if action.target_node_1 in cut_endpoints:
                    continue
                shielded_nodes.add(action.target_node_1)
            elif action.kind == "cut":
                assert action.target_node_2 is not None
                if (
                    action.target_node_1 in shielded_nodes
                    or action.target_node_2 in shielded_nodes
                ):
                    continue
                cut_endpoints.update((action.target_node_1, action.target_node_2))
            accepted.append(candidate_id)
            remaining -= cost
        return accepted


__all__ = [
    "BatchCommander",
    "BatchPlan",
    "ControllerState",
    "DeterministicScout",
    "GraphAnalyst",
    "MAX_LLM_CALLS",
    "RuntimeController",
    "infer_node_count",
]

# End inline: src/starnet/runtime/controller.py

# Begin inline: src/starnet/submission/starnet_model.py
"""赛方入口：保留 CaseVO 编排，把策略计算委托给可测试的纯 Python 控制器。"""


import threading
from typing import Any

import networkx as nx
from agent_mesa import AgentBase, JsonStep, ModelBase



class BaseStarAgent(AgentBase):
    """没有自主环境权限的角色基类，所有实际动作都由控制器再次校验。"""

    def step(self) -> None:
        return None


class ScoutAgent(BaseStarAgent):
    """已注册的侦察角色；固定 ID 扫描由 DeterministicScout 完成。"""


class GraphAnalystAgent(BaseStarAgent):
    """已注册的图分析角色；NetworkX 计算在 Python 控制器中保持确定性。"""


class CommanderAgent(BaseStarAgent):
    """只允许 LLM 对 Python 生成的候选 ID 批次排序。"""

    def __init__(self, unique_id: int, model: ModelBase, description: dict[str, Any]) -> None:
        super().__init__(unique_id, model, description, None)
        self.setup_chain(
            {"rank": [JsonStep(0, self.model.prompt_factory.get_template("commander_react.txt"))]}
        )
        self._lock = threading.Lock()

    def rank_candidates(self, payload: dict[str, Any]) -> object:
        """返回 JsonStep 已解析的 JSON；异常交由控制器走确定性回退。"""
        with self._lock:
            self.chains["rank"].set_input(payload)
            self.chains["rank"].run_step()
            return self.chains["rank"].get_output().get("json")


class ParticipantSquadModel(ModelBase):
    """官方固定签名的模型入口。"""

    def __init__(self, host_env: object, person_list: list[dict[str, Any]], llm: object) -> None:
        agent_graph = nx.Graph()
        agent_graph.add_nodes_from((0, 1, 2))
        agent_graph.add_edges_from(((0, 1), (1, 2)))
        super().__init__(agent_graph, llm)
        self.env = host_env

        descriptions = list(person_list)
        while len(descriptions) < 3:
            descriptions.append({"role": "星网策略角色"})
        self.scout_agent = ScoutAgent(0, self, descriptions[0], None)
        self.analyst_agent = GraphAnalystAgent(1, self, descriptions[1], None)
        self.commander_agent = CommanderAgent(2, self, descriptions[2])
        self.add_agent(self.scout_agent, 0)
        self.add_agent(self.analyst_agent, 1)
        self.add_agent(self.commander_agent, 2)

        self.controller = RuntimeController(
            host_env,
            llm_ranker=self.commander_agent.rank_candidates,
        )

    def step(self) -> int:
        result = self.controller.step()
        if self.controller.last_action_attempted:
            self.schedule.time += 1
        return result

# End inline: src/starnet/submission/starnet_model.py

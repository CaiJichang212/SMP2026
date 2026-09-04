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
    comm_left: int | None

    @classmethod
    def from_scan(cls, payload: dict[str, Any]) -> "NodeState":
        required = {"w", "persona", "neighbors"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"扫描结果缺少字段: {sorted(missing)}")
        raw_comm_left = payload.get("comm_left")
        if raw_comm_left is None:
            comm_left = None
        elif isinstance(raw_comm_left, bool) or not isinstance(raw_comm_left, int):
            raise ValueError("扫描结果中的 comm_left 必须是整数或缺失")
        else:
            comm_left = max(0, raw_comm_left)
        return cls(
            w=float(payload["w"]),
            persona=str(payload["persona"]),
            comm_left=comm_left,
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
        if node.comm_left is not None:
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
            and node.comm_left is not None
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

# Begin inline: src/starnet/policy/config.py
"""Immutable, auditable switches for V0 policy experiments.

The submission always uses :data:`DEFAULT_POLICY_CONFIG`.  Experiment tools may
pass another instance to ``RuntimeController`` without changing the official
``ParticipantSquadModel(host_env, person_list, llm)`` contract.
"""


from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyConfig:
    """All V0 tuning knobs, deliberately small and serialisable.

    ``max_llm_calls`` is the V0 experiment budget, not a replacement for the
    contest-wide 120/250 hard caps.  The controller enforces both.
    """

    shield_threshold: float = 0.55
    cut_threshold: float = 0.20
    enable_shield: bool = True
    enable_cut: bool = True
    enable_communicate: bool = True
    p0_exclusive: bool = True
    mixed_raw_roi: bool = False
    max_llm_calls: int = 3
    stop_after_scan: bool = False
    max_steps: int | None = None

    def __post_init__(self) -> None:
        for name in ("shield_threshold", "cut_threshold"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative number")
        if isinstance(self.max_llm_calls, bool) or self.max_llm_calls < 0:
            raise ValueError("max_llm_calls must be a non-negative integer")
        if self.max_steps is not None and (
            isinstance(self.max_steps, bool) or self.max_steps <= 0
        ):
            raise ValueError("max_steps must be a positive integer or None")

    def safety_step_limit(self, node_count: int) -> int:
        """Return the conservative local cap for the current contest tier."""
        if self.max_steps is not None:
            return self.max_steps
        return 115 if node_count <= 50 else 245

    def contest_llm_limit(self, node_count: int) -> int:
        """The public per-seed LLM cap (preliminary/final respectively)."""
        return 120 if node_count <= 50 else 250


DEFAULT_POLICY_CONFIG = PolicyConfig()

# End inline: src/starnet/policy/config.py

# Begin inline: src/starnet/runtime/env_adapter.py
"""环境调用的单一入口：只使用赛题公开 API，并以返回值更新黑板。"""


from dataclasses import dataclass
from typing import Any, Protocol



class StarNetEnvironment(Protocol):
    def scan_node(self, node_id: int) -> dict[str, Any] | None: ...
    def communicate(self, node_id: int, prompt_id: int) -> dict[str, Any]: ...
    def cut_link(self, left: int, right: int) -> bool: ...
    def shield_node(self, node_id: int) -> bool: ...


@dataclass(frozen=True)
class ActionOutcome:
    """Detailed result of one public environment action.

    ``raw_response`` is intentionally preserved for a local trace.  It is not
    interpreted beyond the existing Blackboard update rules and is never
    emitted by the submission unless an external caller attaches a trace.
    """

    action: Action
    succeeded: bool
    raw_response: Any = None
    rejected_reason: str | None = None


def apply_action_outcome(
    env: StarNetEnvironment, blackboard: Blackboard, action: Action, budget: float
) -> ActionOutcome:
    """Run one legal action and retain the raw public response for diagnostics."""
    if not is_legal_action(action, blackboard, budget):
        return ActionOutcome(action=action, succeeded=False, rejected_reason="illegal_action")

    if action.kind == "scan":
        response = env.scan_node(action.target_node_1)
        return ActionOutcome(
            action=action,
            succeeded=blackboard.record_scan(action.target_node_1, response),
            raw_response=response,
        )
    if action.kind == "comm":
        assert action.prompt_id is not None
        response = env.communicate(action.target_node_1, action.prompt_id)
        return ActionOutcome(
            action=action,
            succeeded=blackboard.record_communication(action.target_node_1, response),
            raw_response=response,
        )
    if action.kind == "cut":
        assert action.target_node_2 is not None
        response = env.cut_link(action.target_node_1, action.target_node_2)
        return ActionOutcome(
            action=action,
            succeeded=blackboard.record_cut(action.target_node_1, action.target_node_2, response),
            raw_response=response,
        )
    if action.kind == "shield":
        response = env.shield_node(action.target_node_1)
        return ActionOutcome(
            action=action,
            succeeded=blackboard.record_shield(action.target_node_1, response),
            raw_response=response,
        )
    return ActionOutcome(action=action, succeeded=False, rejected_reason="unknown_action")


def apply_action(
    env: StarNetEnvironment, blackboard: Blackboard, action: Action, budget: float
) -> bool:
    """执行已校验动作；失败路径不虚构状态，也不访问环境私有成员。"""
    return apply_action_outcome(env, blackboard, action, budget).succeeded


__all__ = ["ActionOutcome", "StarNetEnvironment", "apply_action", "apply_action_outcome"]

# End inline: src/starnet/runtime/env_adapter.py

# Begin inline: src/starnet/runtime/trace.py
"""Best-effort structured diagnostics for local StarNet runs.

The trace is deliberately a side channel: a failed sink is disabled and never
allowed to affect controller decisions or environment calls.  Submission code
does not create a trace; local tools inject one before the first ``step``.
"""


from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Protocol


TRACE_SCHEMA_VERSION = 1
_REDACTED = "[REDACTED]"
_TRUNCATED = "...[truncated]"
_MAX_STRING_LENGTH = 2_000
_MAX_ERROR_LENGTH = 500
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "headers",
    "password",
    "secret",
    "token",
)
_BEARER_VALUE = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|token)\s*[=:]\s*[^\s,;]+"
)


class TraceSink(Protocol):
    """One destination for already structured trace records."""

    def emit(self, record: Mapping[str, Any]) -> None: ...


def _safe_string(value: str, limit: int = _MAX_STRING_LENGTH) -> str:
    value = _BEARER_VALUE.sub(r"\1" + _REDACTED, value)
    value = _SECRET_ASSIGNMENT.sub(r"\1=" + _REDACTED, value)
    return value if len(value) <= limit else value[:limit] + _TRUNCATED


def safe_json_value(value: Any, *, _key: str | None = None) -> Any:
    """Return a JSON-safe, bounded and credential-redacted representation."""
    normalized_key = "" if _key is None else _key.lower().replace("-", "_")
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return _REDACTED
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _safe_string(value)
    if isinstance(value, bytes):
        return _safe_string(value.decode("utf-8", errors="replace"))
    if isinstance(value, Enum):
        return safe_json_value(value.value, _key=_key)
    if is_dataclass(value) and not isinstance(value, type):
        return safe_json_value(asdict(value), _key=_key)
    if isinstance(value, Mapping):
        return {
            _safe_string(str(key), 200): safe_json_value(item, _key=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (set, frozenset)):
        return [safe_json_value(item) for item in sorted(value, key=repr)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [safe_json_value(item) for item in value]
    return _safe_string(f"<{type(value).__name__}>", 200)


def safe_error(exc: BaseException) -> dict[str, str]:
    """Keep useful exception context without serializing exception internals."""
    return {
        "type": type(exc).__name__,
        "message": _safe_string(str(exc), _MAX_ERROR_LENGTH),
    }


class JsonlTraceSink:
    """Append one flushed JSON document per event to a local file."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("a", encoding="utf-8")

    def emit(self, record: Mapping[str, Any]) -> None:
        self._file.write(json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False))
        self._file.write("\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class ConsoleTraceSink:
    """Compact local progress display, intentionally limited to outer steps."""

    def __init__(self, stream: Any | None = None) -> None:
        self.stream = sys.stdout if stream is None else stream

    def emit(self, record: Mapping[str, Any]) -> None:
        if record.get("event") != "step.completed":
            return
        data = record.get("data")
        if not isinstance(data, Mapping):
            return
        action = data.get("action")
        if isinstance(action, Mapping):
            action_text = str(action.get("kind", "action"))
            target = action.get("target_node_1")
            if target is not None:
                action_text += f":{target}"
            second = action.get("target_node_2")
            if second is not None:
                action_text += f"-{second}"
        else:
            action_text = "none"
        result = data.get("action_result", "idle")
        old_state = data.get("state_before", record.get("state"))
        new_state = record.get("state")
        selected = data.get("selected_candidate_ids")
        selected_text = ""
        if isinstance(selected, list) and selected:
            selected_text = f" selected={','.join(str(item) for item in selected)}"
        print(
            f"step={record.get('step')} {old_state}->{new_state} "
            f"action={action_text} budget={record.get('budget_before')}->{record.get('budget_after')} "
            f"result={result}{selected_text}",
            file=self.stream,
            flush=True,
        )


class RuntimeTrace:
    """Fan out ordered trace events while quarantining faulty destinations."""

    def __init__(
        self,
        *,
        run_id: str,
        seed_id: str,
        sinks: Sequence[TraceSink] = (),
    ) -> None:
        self.run_id = str(run_id)
        self.seed_id = str(seed_id)
        self._sinks: list[TraceSink] = list(sinks)
        self._sequence = 0

    @property
    def enabled(self) -> bool:
        return bool(self._sinks)

    @property
    def sequence(self) -> int:
        return self._sequence

    def emit(
        self,
        event: str,
        *,
        step: int,
        state: object,
        budget_before: float | None,
        budget_after: float | None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        if not self._sinks:
            return
        self._sequence += 1
        try:
            record = {
                "schema_version": TRACE_SCHEMA_VERSION,
                "run_id": self.run_id,
                "seed_id": self.seed_id,
                "seq": self._sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
                "event": str(event),
                "step": int(step),
                "state": safe_json_value(state),
                "budget_before": safe_json_value(budget_before),
                "budget_after": safe_json_value(budget_after),
                "data": safe_json_value(data or {}),
            }
        except Exception:
            # If a caller supplies an unserializable diagnostic object, all
            # destinations are disabled instead of leaking into strategy flow.
            self.close()
            return
        healthy: list[TraceSink] = []
        for sink in self._sinks:
            try:
                sink.emit(record)
            except Exception:
                # A trace sink is diagnostic only.  Do not recursively report its failure.
                close = getattr(sink, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            else:
                healthy.append(sink)
        self._sinks = healthy

    def close(self) -> None:
        for sink in self._sinks:
            close = getattr(sink, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._sinks = []


class NullRuntimeTrace(RuntimeTrace):
    """Allocation-free controller default used by the submission entry point."""

    def __init__(self) -> None:
        super().__init__(run_id="", seed_id="", sinks=())


__all__ = [
    "ConsoleTraceSink",
    "JsonlTraceSink",
    "NullRuntimeTrace",
    "RuntimeTrace",
    "TRACE_SCHEMA_VERSION",
    "TraceSink",
    "safe_error",
    "safe_json_value",
]

# End inline: src/starnet/runtime/trace.py

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


def _marginal_factor(comm_left: int | None) -> float:
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


@dataclass(frozen=True)
class LlmParseResult:
    """Validated LLM selection and the observable reason for any fallback."""

    candidate_ids: tuple[str, ...]
    accepted: bool
    fallback_reason: str | None = None


def _candidate_sort_key(
    candidate: Candidate, *, mixed_raw_roi: bool = False
) -> tuple[int, float, float, str]:
    """计划规定的稳定候选排序。"""
    return (
        0 if mixed_raw_roi else candidate.priority,
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
    config: PolicyConfig,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for node_id, node in sorted(blackboard.nodes.items()):
        metrics = _node_metric(analysis, node_id)
        if metrics is None or node.persona != "暴力" or node.w >= 0.0:
            continue
        danger = _finite_nonnegative(metrics.danger)
        if danger < config.shield_threshold:
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
    return sorted(
        candidates,
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )[:MAX_PRIORITY_CANDIDATES[0]]


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
    config: PolicyConfig,
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
        if cut_score < config.cut_threshold:
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
    return sorted(
        candidates,
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )[:MAX_PRIORITY_CANDIDATES[1]]


def _communicate_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object],
    config: PolicyConfig,
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
    return sorted(
        candidates,
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )[:MAX_PRIORITY_CANDIDATES[2]]


def generate_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object] = (),
    config: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> list[Candidate]:
    """从当前黑板和图指标生成稳定、已校验的候选集。

    P0 出现时，本轮只暴露 P0。拓扑或节点状态改变后的下一轮会重新生成 P1/P2，
    因此高危屏蔽不会被普通增益动作延后。
    """
    failed = frozenset(failed_actions)
    shields = (
        _shield_candidates(analysis, blackboard, budget, failed, config)
        if config.enable_shield
        else []
    )
    if shields and config.p0_exclusive:
        return shields[:MAX_CANDIDATES]

    cuts = (
        _cut_candidates(analysis, blackboard, budget, failed, config)
        if config.enable_cut
        else []
    )
    communications = (
        _communicate_candidates(analysis, blackboard, budget, failed, config)
        if config.enable_communicate
        else []
    )
    candidates = shields + cuts + communications
    return sorted(
        candidates,
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )[:MAX_CANDIDATES]


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
    candidates: Iterable[Candidate], budget: float, limit: int = MAX_BATCH_SIZE,
    *, config: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> list[str]:
    """规则回退：按稳定优先级取预算内、互不冲突的动作。"""
    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    ordered = sorted(
        candidate_map.values(),
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )
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
    *,
    config: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> list[str]:
    """解析 Commander 的 JSON；任意无效或空结果均回退到确定性批次。"""
    return list(parse_llm_batch_detailed(payload, candidate_map, budget, config=config).candidate_ids)


def parse_llm_batch_detailed(
    payload: str | bytes | Mapping[str, Any] | None,
    candidate_map: Mapping[str, Candidate],
    budget: float,
    *,
    config: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> LlmParseResult:
    """Parse a Commander result while retaining a precise fallback category."""
    fallback = select_deterministic_batch(candidate_map.values(), budget, config=config)
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return LlmParseResult(tuple(fallback), False, "invalid_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return LlmParseResult(tuple(fallback), False, "invalid_json")
    if not isinstance(payload, Mapping):
        return LlmParseResult(tuple(fallback), False, "invalid_json")

    mode = payload.get("mode")
    candidate_ids = payload.get("candidate_ids")
    if mode not in VALID_BATCH_MODES or not isinstance(candidate_ids, list):
        return LlmParseResult(tuple(fallback), False, "invalid_json")
    if not candidate_ids:
        return LlmParseResult(tuple(fallback), False, "empty_selection")

    selected = _valid_batch_ids(candidate_ids, candidate_map, budget, MAX_BATCH_SIZE)
    if selected:
        return LlmParseResult(tuple(selected), True)
    known_ids = [candidate_id for candidate_id in candidate_ids if isinstance(candidate_id, str)]
    reason = "unknown_candidate" if not any(candidate_id in candidate_map for candidate_id in known_ids) else "empty_selection"
    return LlmParseResult(tuple(fallback), False, reason)


__all__ = [
    "Candidate",
    "LlmParseResult",
    "MAX_BATCH_SIZE",
    "MAX_CANDIDATES",
    "VALID_BATCH_MODES",
    "generate_candidates",
    "parse_llm_batch",
    "parse_llm_batch_detailed",
    "select_deterministic_batch",
]

# End inline: src/starnet/policy/candidates.py

# Begin inline: src/starnet/runtime/controller.py
"""Deterministic scan, analysis, and batch execution state machine.

The controller is independent of ``casevo``. A local caller may attach a
``RuntimeTrace`` after constructing its model and before the first ``step``;
without that explicit injection all trace paths are inert.
"""


from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence



MAX_LLM_CALLS = 3
MAX_BATCH_ACTIONS = 10
MAX_CONSECUTIVE_INVALID = 3


class ControllerState(str, Enum):
    """Explicit controller state, observable by the submission host."""

    INIT = "INIT"
    SCAN_ALL = "SCAN_ALL"
    ANALYZE = "ANALYZE"
    PLAN_BATCH = "PLAN_BATCH"
    EXECUTE = "EXECUTE"
    REANALYZE = "REANALYZE"
    STOP = "STOP"


class StopReason(str, Enum):
    """De-identified reasons for normal controller termination."""

    NO_CANDIDATES = "no_candidates"
    INSUFFICIENT_BUDGET = "insufficient_budget"
    NO_VALID_ACTIONS = "no_valid_actions"
    STATE_GUARD = "state_guard"
    STEP_LIMIT = "step_limit"
    RUNNER_ERROR = "runner_error"


def infer_node_count(initial_budget: float) -> int:
    """Infer the competition network tier from the public starting budget."""
    return 100 if initial_budget >= 150.0 else 50


class DeterministicScout:
    """Scan fixed node IDs in order and never call an LLM."""

    def __init__(self, node_count: int) -> None:
        if node_count <= 0:
            raise ValueError("node_count 必须为正整数")
        self.node_count = node_count
        self._next_node_id = 1

    @property
    def exhausted(self) -> bool:
        return self._next_node_id > self.node_count

    def next_action(self, blackboard: Blackboard) -> Action | None:
        """Return the next unknown ID scan; known IDs are not requested again."""
        while self._next_node_id <= self.node_count:
            node_id = self._next_node_id
            self._next_node_id += 1
            if blackboard.can_scan(node_id):
                return Action("scan", node_id)
        return None


class GraphAnalyst:
    """Thin role wrapper retained for a clear single-file submission boundary."""

    def analyze(self, blackboard: Blackboard) -> GraphAnalysis:
        return analyze_graph(blackboard)

    def generate_candidates(
        self,
        analysis: GraphAnalysis,
        blackboard: Blackboard,
        budget: float,
        failed_actions: set[str],
        config: PolicyConfig,
    ) -> list[Candidate]:
        return generate_candidates(analysis, blackboard, budget, failed_actions, config)


LlmRanker = Callable[[dict[str, Any]], object]


@dataclass(frozen=True)
class BatchPlan:
    """A candidate queue plus the exact source of its ordering."""

    candidate_ids: tuple[str, ...]
    source: str
    fallback_reason: str | None = None
    request_payload: Mapping[str, Any] | None = None
    raw_response: object | None = None
    parsed_candidate_ids: tuple[str, ...] = ()
    error: Mapping[str, str] | None = None

    @property
    def used_llm(self) -> bool:
        """Compatibility alias for the prior two-state plan API."""
        return self.source == "llm"


@dataclass(frozen=True)
class QueueValidation:
    candidate_ids: tuple[str, ...]
    discarded: tuple[dict[str, str], ...]


class BatchCommander:
    """Use an LLM only to order Python-validated candidates, with fallback."""

    def __init__(
        self,
        llm_ranker: LlmRanker | None = None,
        *,
        config: PolicyConfig = DEFAULT_POLICY_CONFIG,
        contest_llm_limit: int | None = None,
    ) -> None:
        self.llm_ranker = llm_ranker
        self.config = config
        self.max_llm_calls = min(
            config.max_llm_calls,
            contest_llm_limit if contest_llm_limit is not None else config.max_llm_calls,
        )
        self.llm_calls = 0

    @property
    def can_request_llm(self) -> bool:
        return self.llm_ranker is not None and self.llm_calls < self.max_llm_calls

    def preview_payload(
        self,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
    ) -> dict[str, Any]:
        """Build the exact payload for the next request without consuming quota."""
        return self._build_payload(candidates, budget, analysis, self.llm_calls + 1)

    def plan(
        self,
        *,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
        request_payload: Mapping[str, Any] | None = None,
    ) -> BatchPlan:
        candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
        fallback = tuple(select_deterministic_batch(candidates, budget, MAX_BATCH_ACTIONS, config=self.config))
        if not candidate_map:
            return BatchPlan(fallback, "deterministic_fallback", "no_candidates")
        if self.llm_ranker is None:
            return BatchPlan(fallback, "deterministic_fallback", "no_llm_ranker")
        if self.llm_calls >= self.max_llm_calls:
            return BatchPlan(fallback, "quota_exhausted", "quota_exhausted")

        # Quota is consumed before the external call, including a timeout.
        self.llm_calls += 1
        payload = dict(request_payload or self._build_payload(candidates, budget, analysis, self.llm_calls))
        try:
            raw_response = self.llm_ranker(payload)
        except Exception as exc:
            return BatchPlan(
                fallback,
                "deterministic_fallback",
                "exception",
                payload,
                error=safe_error(exc),
            )

        parsed = parse_llm_batch_detailed(raw_response, candidate_map, budget, config=self.config)
        if parsed.accepted:
            return BatchPlan(
                parsed.candidate_ids,
                "llm",
                request_payload=payload,
                raw_response=raw_response,
                parsed_candidate_ids=parsed.candidate_ids,
            )
        return BatchPlan(
            parsed.candidate_ids,
            "deterministic_fallback",
            parsed.fallback_reason,
            payload,
            raw_response,
            parsed.candidate_ids,
        )

    def _build_payload(
        self,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
        llm_call_number: int,
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
            "llm_calls": llm_call_number,
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
                    "score": candidate.score,
                    "roi": candidate.roi,
                    "reason": candidate.reason,
                }
                for candidate in candidates
            ],
        }


class RuntimeController:
    """V0 state machine; each ``step`` performs at most one environment action."""

    def __init__(
        self,
        env: StarNetEnvironment,
        llm_ranker: LlmRanker | None = None,
        *,
        initial_budget: float | None = None,
        node_count: int | None = None,
        blackboard: Blackboard | None = None,
        config: PolicyConfig = DEFAULT_POLICY_CONFIG,
    ) -> None:
        self.env = env
        self.blackboard = blackboard if blackboard is not None else Blackboard()
        self.initial_budget = float(
            env.get_remaining_budget() if initial_budget is None else initial_budget
        )
        self.node_count = infer_node_count(self.initial_budget) if node_count is None else node_count
        self.config = config
        self.scout = DeterministicScout(self.node_count)
        self.analyst = GraphAnalyst()
        # The experiment may forbid LLM use even when the official model has a ranker.
        self.commander = BatchCommander(
            llm_ranker if config.max_llm_calls else None,
            config=config,
            contest_llm_limit=config.contest_llm_limit(self.node_count),
        )
        self.state = ControllerState.INIT
        self.analysis: GraphAnalysis | None = None
        self.candidates: dict[str, Candidate] = {}
        self.queue: list[str] = []
        self.failed_actions: set[str] = set()
        self.consecutive_invalid = 0
        self.last_action_attempted = False
        self.last_action_succeeded: bool | None = None
        self.last_action_error: str | None = None
        self.action_attempts = 0
        self.action_successes = 0
        self.action_failures = 0
        self.stop_reason: StopReason | None = None
        self._trace: RuntimeTrace = NullRuntimeTrace()
        self._step_number = 0
        self._last_trace_budget_after: float | None = None
        self._last_step_action: dict[str, Any] | None = None
        self._last_step_action_result = "idle"
        self._last_step_selected_ids: list[str] = []

    @property
    def llm_calls(self) -> int:
        return self.commander.llm_calls

    @property
    def stopped(self) -> bool:
        return self.state is ControllerState.STOP

    @property
    def step_number(self) -> int:
        return self._step_number

    def attach_trace(self, trace: RuntimeTrace) -> None:
        """Attach optional local diagnostics before the first controller step."""
        self._trace = trace
        self._emit(
            "run.started",
            self.initial_budget,
            self.initial_budget,
            {
                "node_count": self.scout.node_count,
                "initial_budget": self.initial_budget,
                "max_llm_calls": self.commander.max_llm_calls,
                "safety_step_limit": self.config.safety_step_limit(self.node_count),
                "max_batch_actions": MAX_BATCH_ACTIONS,
            },
        )

    def stop_for_step_limit(self) -> None:
        """Record a local runner's explicit safety cap as a normal stop event."""
        if not self.stopped:
            self._stop(StopReason.STEP_LIMIT, self._current_budget())

    def stop_for_runner_error(self) -> None:
        """Record a local runner abort without relying on a private environment API."""
        if not self.stopped:
            self._stop(StopReason.RUNNER_ERROR, self._current_budget())

    def record_evaluation(self, score: object, *, budget_before: float | None = None) -> None:
        """Let a local runner append the public evaluation result to the trace."""
        if not self._trace.enabled:
            return
        before = self._current_budget() if budget_before is None else budget_before
        after = self._trace_budget_after(before)
        self._emit(
            "evaluation.completed",
            before,
            after,
            {
                "score": score,
                "action_attempts": self.action_attempts,
                "action_successes": self.action_successes,
                "action_failures": self.action_failures,
                "remaining_budget": after,
                "stop_reason": self.stop_reason.value if self.stop_reason else None,
            },
        )

    def step(self) -> int:
        """Advance the state machine; diagnostics never control this flow."""
        # This consumes the last permitted outer call as a stop-only call.  It
        # leaves five calls of headroom beneath the published 120/250 limits.
        if self._step_number + 1 >= self.config.safety_step_limit(self.node_count):
            self._step_number += 1
            self._stop(StopReason.STEP_LIMIT, self._current_budget())
            return self._complete_step(1, self.state.value, self._current_budget())
        self._step_number += 1
        state_before = self.state.value
        budget_before = self._current_budget()
        self.last_action_attempted = False
        self.last_action_succeeded = None
        self.last_action_error = None
        self._last_trace_budget_after = None
        self._last_step_action = None
        self._last_step_action_result = "idle"
        self._last_step_selected_ids = []
        self._emit(
            "step.started",
            budget_before,
            budget_before,
            {"state_before": state_before, "action_attempts": self.action_attempts},
        )

        # State transitions have no environment action, so they may be consumed
        # in this dispatch slot until one public request is needed.
        for _ in range(8):
            if self.state is ControllerState.STOP:
                return self._complete_step(1, state_before, budget_before)

            budget = self._current_budget()
            if self.state is ControllerState.INIT:
                self._transition(ControllerState.SCAN_ALL, "initialized", budget)
                continue

            if self.state is ControllerState.SCAN_ALL:
                result = self._scan_next(budget)
                return self._complete_step(result, state_before, budget_before)

            if self.state is ControllerState.ANALYZE:
                self._refresh_candidates(budget, "analyze")
                if self.candidates:
                    self._transition(ControllerState.PLAN_BATCH, "candidates_generated", budget)
                else:
                    self._stop(StopReason.NO_CANDIDATES, budget)
                continue

            if self.state is ControllerState.PLAN_BATCH:
                if self.analysis is None or not self.candidates:
                    self._stop(StopReason.NO_CANDIDATES, budget)
                    continue
                self._create_plan(budget)
                if self.queue:
                    self._transition(ControllerState.EXECUTE, "validated_queue_available", budget)
                else:
                    self._stop(StopReason.NO_VALID_ACTIONS, budget)
                continue

            if self.state is ControllerState.EXECUTE:
                result = self._execute_next(budget)
                return self._complete_step(result, state_before, budget_before)

            if self.state is ControllerState.REANALYZE:
                self._refresh_candidates(budget, "reanalyze")
                previous_queue = self.queue
                validation = self._valid_queue(previous_queue, budget)
                self.queue = list(validation.candidate_ids)
                self._emit_queue_revalidated("reanalysis", validation, budget)
                invalidated = len(previous_queue) - len(self.queue)
                if invalidated:
                    self.consecutive_invalid += invalidated
                if previous_queue and invalidated * 2 > len(previous_queue):
                    self.queue.clear()
                    self._emit(
                        "queue.revalidated",
                        budget,
                        budget,
                        {
                            "source": "reanalysis",
                            "enqueued_candidate_ids": [],
                            "discarded": [
                                {"candidate_id": candidate_id, "reason": "majority_invalidated"}
                                for candidate_id in validation.candidate_ids
                            ],
                        },
                    )
                if self.consecutive_invalid >= MAX_CONSECUTIVE_INVALID:
                    self.queue.clear()
                    self.consecutive_invalid = 0
                if self.queue:
                    self._transition(ControllerState.EXECUTE, "queue_revalidated", budget)
                elif self.candidates:
                    self._transition(ControllerState.PLAN_BATCH, "queue_empty_after_reanalysis", budget)
                else:
                    self._stop(StopReason.NO_VALID_ACTIONS, budget)
                continue

        self._stop(StopReason.STATE_GUARD, self._current_budget())
        return self._complete_step(1, state_before, budget_before)

    def _scan_next(self, budget: float) -> int:
        action = self.scout.next_action(self.blackboard)
        if action is None:
            self._transition(ControllerState.ANALYZE, "scan_exhausted", budget)
            self._emit("scan.completed", budget, budget, {"blackboard": self.blackboard.snapshot()})
            return 0
        if not is_legal_action(action, self.blackboard, budget):
            self._stop(StopReason.INSUFFICIENT_BUDGET, budget)
            return 1

        self._attempt_action(action, f"scan:{action.target_node_1}", budget)
        if self.scout.exhausted:
            completed_budget = (
                self._last_trace_budget_after
                if self._last_trace_budget_after is not None
                else budget
            )
            if self.config.stop_after_scan:
                self._stop(StopReason.NO_CANDIDATES, completed_budget)
            else:
                self._transition(ControllerState.ANALYZE, "scan_complete", completed_budget)
            self._emit(
                "scan.completed",
                budget,
                completed_budget,
                {"blackboard": self.blackboard.snapshot()},
            )
        return 0

    def _execute_next(self, budget: float) -> int:
        if not self.queue:
            self._transition(ControllerState.REANALYZE, "queue_depleted", budget)
            return 0

        candidate_id = self.queue.pop(0)
        candidate = self.candidates.get(candidate_id)
        if candidate is None or candidate_id in self.failed_actions:
            self.consecutive_invalid += 1
            self._emit(
                "queue.revalidated",
                budget,
                budget,
                {
                    "source": "execute",
                    "enqueued_candidate_ids": list(self.queue),
                    "discarded": [{"candidate_id": candidate_id, "reason": "failed_or_unknown"}],
                },
            )
            self._transition(ControllerState.REANALYZE, "candidate_unavailable", budget)
            return 0
        if not is_legal_action(candidate.action, self.blackboard, budget):
            self.consecutive_invalid += 1
            self._emit(
                "queue.revalidated",
                budget,
                budget,
                {
                    "source": "execute",
                    "enqueued_candidate_ids": list(self.queue),
                    "discarded": [{"candidate_id": candidate_id, "reason": "illegal_action"}],
                },
            )
            self._transition(ControllerState.REANALYZE, "candidate_illegal", budget)
            return 0

        success = self._attempt_action(candidate.action, candidate_id, budget)
        if success:
            self.consecutive_invalid = 0
        else:
            self.failed_actions.add(candidate_id)
            self.consecutive_invalid += 1
        self._transition(
            ControllerState.REANALYZE,
            "action_succeeded" if success else "action_failed",
            self._last_trace_budget_after
            if self._last_trace_budget_after is not None
            else budget,
        )
        return 0

    def _attempt_action(self, action: Action, candidate_id: str, budget: float) -> bool:
        self.last_action_attempted = True
        self.action_attempts += 1
        self._last_step_action = asdict(action)
        before_snapshot = self.blackboard.snapshot() if self._trace.enabled else None
        self._emit(
            "action.requested",
            budget,
            budget,
            {"candidate_id": candidate_id, "action": asdict(action)},
        )
        try:
            outcome = apply_action_outcome(self.env, self.blackboard, action, budget)
        except Exception as exc:
            self.last_action_succeeded = False
            self.last_action_error = type(exc).__name__
            self.action_failures += 1
            self._last_step_action_result = "exception"
            budget_after = self._trace_budget_after(budget)
            self._emit(
                "action.failed",
                budget,
                budget_after,
                {
                    "candidate_id": candidate_id,
                    "action": asdict(action),
                    "error": safe_error(exc),
                    "blackboard": self.blackboard.snapshot(),
                },
            )
            return False

        self.last_action_succeeded = outcome.succeeded
        budget_after = self._trace_budget_after(budget)
        if outcome.succeeded:
            self.action_successes += 1
            self._last_step_action_result = "success"
            self._emit(
                "action.completed",
                budget,
                budget_after,
                self._action_trace_data(candidate_id, outcome, before_snapshot),
            )
            return True

        self.action_failures += 1
        self._last_step_action_result = "failed"
        self._emit(
            "action.failed",
            budget,
            budget_after,
            self._action_trace_data(candidate_id, outcome, before_snapshot),
        )
        return False

    def _action_trace_data(
        self,
        candidate_id: str,
        outcome: ActionOutcome,
        before_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "candidate_id": candidate_id,
            "action": asdict(outcome.action),
            "raw_response": outcome.raw_response,
            "success": outcome.succeeded,
            "rejected_reason": outcome.rejected_reason,
        }
        if before_snapshot is not None:
            data["blackboard_delta"] = self._blackboard_delta(
                before_snapshot, self.blackboard.snapshot()
            )
        return data

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        self.analysis = self.analyst.analyze(self.blackboard)
        candidates = self.analyst.generate_candidates(
            self.analysis,
            self.blackboard,
            budget,
            self.failed_actions,
            self.config,
        )
        self.candidates = {candidate.candidate_id: candidate for candidate in candidates}
        self._emit(
            "analysis.completed",
            budget,
            budget,
            self._analysis_trace_data(self.analysis, phase),
        )
        self._emit(
            "candidates.generated",
            budget,
            budget,
            {
                "phase": phase,
                "filtered_count": len(candidates),
                "candidates": [self._candidate_trace_data(candidate) for candidate in candidates],
            },
        )

    def _create_plan(self, budget: float) -> None:
        assert self.analysis is not None
        candidates = list(self.candidates.values())
        request_payload: Mapping[str, Any] | None = None
        if self.commander.can_request_llm:
            request_payload = self.commander.preview_payload(candidates, budget, self.analysis)
            self._emit(
                "llm.requested",
                budget,
                budget,
                {"payload": request_payload, "llm_call": self.commander.llm_calls + 1},
            )
        plan = self.commander.plan(
            candidates=candidates,
            budget=budget,
            analysis=self.analysis,
            request_payload=request_payload,
        )
        if plan.request_payload is not None and plan.error is None:
            self._emit(
                "llm.completed",
                budget,
                budget,
                {
                    "raw_output": plan.raw_response,
                    "parsed": {
                        "accepted": plan.source == "llm",
                        "candidate_ids": list(plan.parsed_candidate_ids),
                        "fallback_reason": plan.fallback_reason,
                    },
                    "llm_calls": self.commander.llm_calls,
                },
            )
        if plan.source != "llm" and (plan.request_payload is not None or plan.source == "quota_exhausted"):
            self._emit(
                "llm.failed",
                budget,
                budget,
                {
                    "source": plan.source,
                    "fallback_reason": plan.fallback_reason,
                    "error": plan.error,
                    "llm_calls": self.commander.llm_calls,
                },
            )
        validation = self._valid_queue(plan.candidate_ids, budget)
        self.queue = list(validation.candidate_ids)
        self._last_step_selected_ids = list(self.queue)
        self._emit(
            "plan.created",
            budget,
            budget,
            {
                "source": plan.source,
                "fallback_reason": plan.fallback_reason,
                "planned_candidate_ids": list(plan.candidate_ids),
                "selected_candidate_ids": list(self.queue),
                "llm_calls": self.commander.llm_calls,
            },
        )
        self._emit_queue_revalidated("plan", validation, budget)

    def _emit_queue_revalidated(
        self, source: str, validation: QueueValidation, budget: float
    ) -> None:
        self._emit(
            "queue.revalidated",
            budget,
            budget,
            {
                "source": source,
                "enqueued_candidate_ids": list(validation.candidate_ids),
                "discarded": list(validation.discarded),
            },
        )

    def _transition(self, state: ControllerState, reason: str, budget: float) -> None:
        if state is self.state:
            return
        previous = self.state
        self.state = state
        self._emit(
            "state.transition",
            budget,
            budget,
            {"old_state": previous.value, "new_state": state.value, "reason": reason},
        )

    def _stop(self, reason: StopReason, budget: float) -> None:
        if self.state is ControllerState.STOP:
            return
        self.stop_reason = reason
        self._transition(ControllerState.STOP, reason.value, budget)
        final_budget = self._trace_budget_after(budget)
        self._emit(
            "run.stopped",
            budget,
            final_budget,
            {
                "reason": reason.value,
                "blackboard": self.blackboard.snapshot(),
                "action_attempts": self.action_attempts,
                "action_successes": self.action_successes,
                "action_failures": self.action_failures,
                "remaining_budget": final_budget,
                "llm_calls": self.commander.llm_calls,
            },
        )

    def _complete_step(self, result: int, state_before: str, budget_before: float) -> int:
        budget_after = (
            self._last_trace_budget_after
            if self._last_trace_budget_after is not None
            else self._trace_budget_after(budget_before)
        )
        self._emit(
            "step.completed",
            budget_before,
            budget_after,
            {
                "state_before": state_before,
                "return_code": result,
                "action": self._last_step_action,
                "action_result": self._last_step_action_result,
                "action_attempts": self.action_attempts,
                "action_successes": self.action_successes,
                "action_failures": self.action_failures,
                "selected_candidate_ids": self._last_step_selected_ids,
            },
        )
        return result

    def _emit(
        self,
        event: str,
        budget_before: float | None,
        budget_after: float | None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        """Keep all controller records on the trace's best-effort boundary."""
        self._trace.emit(
            event,
            step=self._step_number,
            state=self.state.value,
            budget_before=budget_before,
            budget_after=budget_after,
            data=data,
        )

    def _current_budget(self) -> float:
        return float(self.env.get_remaining_budget())

    def _trace_budget_after(self, fallback: float) -> float:
        if not self._trace.enabled:
            return fallback
        try:
            budget = self._current_budget()
        except Exception:
            budget = fallback
        self._last_trace_budget_after = budget
        return budget

    @staticmethod
    def _candidate_trace_data(candidate: Candidate) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "action": asdict(candidate.action),
            "priority": candidate.priority,
            "score": candidate.score,
            "roi": candidate.roi,
            "reason": candidate.reason,
        }

    @staticmethod
    def _analysis_trace_data(analysis: GraphAnalysis, phase: str) -> dict[str, Any]:
        return {
            "phase": phase,
            "node_count": analysis.node_count,
            "edge_count": analysis.edge_count,
            "community_count": analysis.community_count,
            "node_metrics": {
                node_id: asdict(metrics) for node_id, metrics in sorted(analysis.node_metrics.items())
            },
            "edge_metrics": [
                {"edge": list(edge), **asdict(metrics)}
                for edge, metrics in sorted(analysis.edge_metrics.items())
            ],
        }

    @staticmethod
    def _blackboard_delta(
        before: Mapping[str, Any], after: Mapping[str, Any]
    ) -> dict[str, Any]:
        before_nodes = before.get("nodes", {})
        after_nodes = after.get("nodes", {})
        if not isinstance(before_nodes, Mapping) or not isinstance(after_nodes, Mapping):
            return {}
        before_edges = {tuple(edge) for edge in before.get("edges", [])}
        after_edges = {tuple(edge) for edge in after.get("edges", [])}
        before_dead = set(before.get("dead_nodes", []))
        after_dead = set(after.get("dead_nodes", []))
        common_nodes = set(before_nodes).intersection(after_nodes)
        return {
            "added_nodes": {
                node_id: after_nodes[node_id]
                for node_id in sorted(set(after_nodes).difference(before_nodes))
            },
            "removed_nodes": {
                node_id: before_nodes[node_id]
                for node_id in sorted(set(before_nodes).difference(after_nodes))
            },
            "updated_nodes": {
                node_id: {"before": before_nodes[node_id], "after": after_nodes[node_id]}
                for node_id in sorted(common_nodes)
                if before_nodes[node_id] != after_nodes[node_id]
            },
            "added_edges": [list(edge) for edge in sorted(after_edges.difference(before_edges))],
            "removed_edges": [list(edge) for edge in sorted(before_edges.difference(after_edges))],
            "added_dead_nodes": sorted(after_dead.difference(before_dead)),
            "removed_dead_nodes": sorted(before_dead.difference(after_dead)),
        }

    def _valid_queue(self, candidate_ids: Sequence[object], budget: float) -> QueueValidation:
        """Revalidate plan IDs against current facts, conflicts, and budget."""
        accepted: list[str] = []
        discarded: list[dict[str, str]] = []
        seen: set[str] = set()
        shielded_nodes: set[int] = set()
        cut_endpoints: set[int] = set()
        remaining = budget
        for raw_candidate_id in candidate_ids:
            if not isinstance(raw_candidate_id, str):
                discarded.append({"candidate_id": repr(raw_candidate_id), "reason": "invalid_id"})
                continue
            candidate_id = raw_candidate_id
            if len(accepted) >= MAX_BATCH_ACTIONS:
                discarded.append({"candidate_id": candidate_id, "reason": "batch_limit"})
                continue
            if candidate_id in seen:
                discarded.append({"candidate_id": candidate_id, "reason": "duplicate"})
                continue
            seen.add(candidate_id)
            candidate = self.candidates.get(candidate_id)
            if candidate is None:
                discarded.append({"candidate_id": candidate_id, "reason": "unknown_candidate"})
                continue
            if candidate_id in self.failed_actions:
                discarded.append({"candidate_id": candidate_id, "reason": "failed_action"})
                continue
            action = candidate.action
            cost = action_cost(action)
            if cost > remaining:
                discarded.append({"candidate_id": candidate_id, "reason": "insufficient_budget"})
                continue
            if not is_legal_action(action, self.blackboard, remaining):
                discarded.append({"candidate_id": candidate_id, "reason": "illegal_action"})
                continue
            if action.kind == "shield":
                if action.target_node_1 in cut_endpoints:
                    discarded.append({"candidate_id": candidate_id, "reason": "conflict"})
                    continue
                shielded_nodes.add(action.target_node_1)
            elif action.kind == "cut":
                assert action.target_node_2 is not None
                if action.target_node_1 in shielded_nodes or action.target_node_2 in shielded_nodes:
                    discarded.append({"candidate_id": candidate_id, "reason": "conflict"})
                    continue
                cut_endpoints.update((action.target_node_1, action.target_node_2))
            accepted.append(candidate_id)
            remaining -= cost
        return QueueValidation(tuple(accepted), tuple(discarded))


__all__ = [
    "BatchCommander",
    "BatchPlan",
    "ControllerState",
    "DeterministicScout",
    "GraphAnalyst",
    "MAX_LLM_CALLS",
    "QueueValidation",
    "RuntimeController",
    "StopReason",
    "infer_node_count",
]

# End inline: src/starnet/runtime/controller.py

# Begin inline: src/starnet/submission/starnet_model.py
"""赛方入口：保留 CaseVO 编排，把策略计算委托给可测试的纯 Python 控制器。"""


import threading
from typing import Any

import networkx as nx
from casevo import AgentBase, JsonStep, ModelBase



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

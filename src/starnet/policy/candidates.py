"""候选生成与不依赖 LLM 的批次选择。"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from starnet.model.blackboard import Blackboard, Edge, NodeState, normalize_edge
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.graph_analysis import EdgeMetrics, GraphAnalysis, NodeMetrics


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

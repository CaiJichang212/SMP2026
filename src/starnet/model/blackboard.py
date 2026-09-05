"""仅保存环境已公开信息的本地黑板。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
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
        raw_w = payload["w"]
        if isinstance(raw_w, bool) or not isinstance(raw_w, (int, float)) or not math.isfinite(raw_w):
            raise ValueError("扫描结果中的 w 必须是有限数值")
        if not isinstance(payload["persona"], str):
            raise ValueError("扫描结果中的 persona 必须是字符串")
        neighbors = payload["neighbors"]
        if not isinstance(neighbors, list) or any(
            isinstance(node_id, bool) or not isinstance(node_id, int) or node_id <= 0
            for node_id in neighbors
        ):
            raise ValueError("扫描结果中的 neighbors 必须是正整数列表")
        raw_comm_left = payload.get("comm_left")
        if raw_comm_left is None:
            comm_left = None
        elif isinstance(raw_comm_left, bool) or not isinstance(raw_comm_left, int):
            raise ValueError("扫描结果中的 comm_left 必须是整数或缺失")
        else:
            comm_left = max(0, raw_comm_left)
        return cls(
            w=float(raw_w),
            persona=payload["persona"],
            comm_left=comm_left,
        )


class Blackboard:
    """Environment facts only, with an append-only action audit trail.

    This deliberately does not contain predictions or LLM prose.  A caller may
    use the snapshot as decision evidence, but every field here must originate
    in an explicit stage contract or a public environment response.
    """

    def __init__(self, node_count: int | None = None) -> None:
        if node_count is not None and (isinstance(node_count, bool) or node_count <= 0):
            raise ValueError("node_count must be a positive integer or None")
        self.node_count = node_count
        self.nodes: dict[int, NodeState] = {}
        self.edges: set[Edge] = set()
        self.dead_nodes: set[int] = set()
        self.shielded_ids: set[int] = set()
        self.nonexistent_ids: set[int] = set()
        self.confirmed_non_edges: set[Edge] = set()
        self.unresolved_nodes: set[int] = set()
        self.budget_units: int | None = None
        self.outer_steps = 0
        self.llm_attempts = 0
        self.env_calls = 0
        self.state_version = 0
        self.events: list[dict[str, Any]] = []

    def can_scan(self, node_id: int) -> bool:
        return (
            node_id > 0
            and (self.node_count is None or node_id <= self.node_count)
            and node_id not in self.nodes
            and node_id not in self.dead_nodes
        )

    @property
    def scanned_ids(self) -> set[int]:
        return set(self.nodes) | set(self.dead_nodes)

    @property
    def frontier_ids(self) -> set[int]:
        return {
            node_id
            for edge in self.edges
            for node_id in edge
            if node_id not in self.scanned_ids and node_id not in self.dead_nodes
        }

    @property
    def unseen_ids(self) -> set[int]:
        if self.node_count is None:
            return set()
        return set(range(1, self.node_count + 1)).difference(self.scanned_ids).difference(self.frontier_ids)

    def set_budget(self, budget: float) -> None:
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget):
            raise ValueError("budget must be a finite number")
        units = round(float(budget) * 2)
        if not math.isclose(float(budget) * 2, units, abs_tol=1e-7):
            raise ValueError("budget must be representable in 0.5 units")
        self.budget_units = max(0, units)

    def record_event(self, kind: str, **data: Any) -> None:
        self.state_version += 1
        self.events.append({"version": self.state_version, "kind": kind, **data})

    def record_scan(self, node_id: int, payload: dict[str, Any] | None) -> bool:
        """写入真实扫描结果；空结果只表示该 ID 当前不可用。"""
        if not self.can_scan(node_id):
            return False
        if payload is None:
            self.dead_nodes.add(node_id)
            self.nonexistent_ids.add(node_id)
            self.record_event("scan", node_id=node_id, status="unavailable")
            return True

        state = NodeState.from_scan(payload)
        self.nodes[node_id] = state
        for neighbor_id in payload["neighbors"]:
            if (
                neighbor_id > 0
                and neighbor_id != node_id
                and (self.node_count is None or neighbor_id <= self.node_count)
            ):
                self.edges.add(normalize_edge(node_id, neighbor_id))
        scanned = set(self.nodes)
        for other_id in scanned.difference({node_id}):
            edge = normalize_edge(node_id, other_id)
            if other_id not in set(payload["neighbors"]):
                self.confirmed_non_edges.add(edge)
        self.record_event("scan", node_id=node_id, status="success")
        return True

    def record_communication(self, node_id: int, response: dict[str, Any]) -> bool:
        """仅在环境报告 success 时更新倾向和可沟通次数。"""
        node = self.nodes.get(node_id)
        if node is None or response.get("status") != "success":
            if node is not None and response.get("status") == "max_comm_reached":
                node.comm_left = 0
                self.record_event("communicate", node_id=node_id, status="max_comm_reached")
            return False
        if "new_w" not in response:
            return False
        node.w = float(response["new_w"])
        raw_comm_left = response.get("comm_left")
        if isinstance(raw_comm_left, int) and not isinstance(raw_comm_left, bool):
            node.comm_left = max(0, raw_comm_left)
        elif node.comm_left is not None:
            node.comm_left = max(0, node.comm_left - 1)
        self.record_event("communicate", node_id=node_id, status="success", new_w=node.w)
        return True

    def record_cut(self, left: int, right: int, success: bool) -> bool:
        if not success:
            return False
        self.edges.discard(normalize_edge(left, right))
        self.record_event("cut", left=left, right=right, status="success")
        return True

    def record_shield(self, node_id: int, success: bool) -> bool:
        if not success or node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        self.edges = {edge for edge in self.edges if node_id not in edge}
        self.dead_nodes.add(node_id)
        self.shielded_ids.add(node_id)
        self.record_event("shield", node_id=node_id, status="success")
        return True

    def snapshot(self) -> dict[str, Any]:
        """为 LLM、日志与回归测试返回可 JSON 序列化的状态快照。"""
        return {
            "nodes": {node_id: asdict(state) for node_id, state in sorted(self.nodes.items())},
            "edges": [list(edge) for edge in sorted(self.edges)],
            "dead_nodes": sorted(self.dead_nodes),
            "shielded_ids": sorted(self.shielded_ids),
            "nonexistent_ids": sorted(self.nonexistent_ids),
            "confirmed_non_edges": [list(edge) for edge in sorted(self.confirmed_non_edges)],
            "frontier_ids": sorted(self.frontier_ids),
            "unseen_ids": sorted(self.unseen_ids),
            "unresolved_nodes": sorted(self.unresolved_nodes),
            "resources": {
                "budget_units": self.budget_units,
                "outer_steps": self.outer_steps,
                "llm_attempts": self.llm_attempts,
                "env_calls": self.env_calls,
            },
            "state_version": self.state_version,
            "events": list(self.events),
        }

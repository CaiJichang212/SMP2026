"""仅保存环境已公开信息的本地黑板。"""

from __future__ import annotations

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

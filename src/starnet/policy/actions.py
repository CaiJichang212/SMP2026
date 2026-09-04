"""动作预算与合法性校验，不依赖 LLM 或真实环境。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from starnet.model.blackboard import Blackboard, normalize_edge


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

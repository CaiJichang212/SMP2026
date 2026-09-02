"""环境调用的单一入口：只使用赛题公开 API，并以返回值更新黑板。"""

from __future__ import annotations

from typing import Any, Protocol

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action


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

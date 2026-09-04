"""环境调用的单一入口：只使用赛题公开 API，并以返回值更新黑板。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action


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

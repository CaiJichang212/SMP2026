"""Development-only high-influence probe-node selector for frozen P11."""

from __future__ import annotations

import math

from starnet.model.blackboard import Blackboard
from starnet.policy.baseline import _public_influence_coefficients
from starnet.runtime.p11_prompt_controller_experiment import PromptLearningRuntimeController


def select_high_influence_prompt_probe_nodes(
    board: Blackboard, *, max_probe_budget: float = 12.0, max_nodes: int = 2,
) -> tuple[int, ...]:
    """Use the same P11 eligibility but rank by public settlement influence."""
    if (not math.isfinite(max_probe_budget) or max_probe_budget < 0
            or isinstance(max_nodes, bool) or max_nodes <= 0):
        raise ValueError("invalid high-influence prompt-probe limits")
    capacity = min(max_nodes, int(max_probe_budget // 6.0))
    if capacity <= 0:
        return ()
    influence = _public_influence_coefficients(board)
    eligible = [
        node_id for node_id, node in board.nodes.items()
        if node.persona in {"和平", "中立"}
        and node.comm_left == 3
        and -60.0 < float(node.w) < 60.0
    ]
    eligible.sort(key=lambda node_id: (
        -influence.get(node_id, 0.0), abs(float(board.nodes[node_id].w)), node_id,
    ))
    return tuple(eligible[:capacity])


class HighInfluencePromptLearningController(PromptLearningRuntimeController):
    """Preselect high-influence probes before frozen P11 performs its first refresh."""

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        if (self.p11_enabled and not self.p11_probe_nodes
                and not self.p11_calibration_finished
                and len(self.blackboard.scanned_ids) == self.node_count):
            self.p11_probe_nodes = select_high_influence_prompt_probe_nodes(
                self.blackboard,
                max_probe_budget=self.p11_max_probe_budget,
                max_nodes=self.p11_max_probe_nodes,
            )
        super()._refresh_candidates(budget, phase)


__all__ = [
    "HighInfluencePromptLearningController",
    "select_high_influence_prompt_probe_nodes",
]

"""Public-feedback-only calibration of hidden prompt-ID correction values."""

from __future__ import annotations

import math
from typing import Mapping

from starnet.model.blackboard import Blackboard


PROMPT_IDS = (1, 2, 3)
TURN_MULTIPLIERS = {1: 1.0, 2: 0.5, 3: 0.25}


def select_prompt_probe_nodes(
    board: Blackboard, *, max_probe_budget: float = 12.0, max_nodes: int = 2,
) -> tuple[int, ...]:
    """Choose low-impact public nodes for complete three-prompt probes."""
    if (not math.isfinite(max_probe_budget) or max_probe_budget < 0
            or isinstance(max_nodes, bool) or max_nodes <= 0):
        raise ValueError("invalid prompt-probe limits")
    capacity = min(max_nodes, int(max_probe_budget // 6.0))
    if capacity <= 0:
        return ()
    degree = {node_id: 0 for node_id in board.nodes}
    for left, right in board.edges:
        if left in degree and right in degree:
            degree[left] += 1
            degree[right] += 1
    eligible = [
        node_id for node_id, node in board.nodes.items()
        if node.persona in {"和平", "中立"}
        and node.comm_left == 3
        and -60.0 < float(node.w) < 60.0
    ]
    eligible.sort(key=lambda node_id: (degree[node_id], abs(board.nodes[node_id].w), node_id))
    return tuple(eligible[:capacity])


class PromptCalibrationLedger:
    """Compare prompt strengths within nodes after removing turn decay."""

    def __init__(self, *, required_complete_nodes: int = 2,
                 tie_tolerance: float = 1e-9, default_prompt_id: int = 1) -> None:
        if (isinstance(required_complete_nodes, bool) or required_complete_nodes <= 0
                or not math.isfinite(tie_tolerance) or tie_tolerance < 0
                or default_prompt_id not in PROMPT_IDS):
            raise ValueError("invalid prompt calibration configuration")
        self.required_complete_nodes = required_complete_nodes
        self.tie_tolerance = tie_tolerance
        self.default_prompt_id = default_prompt_id
        self.accepted: list[dict[str, object]] = []
        self.censored: list[dict[str, object]] = []
        self.failures: list[dict[str, object]] = []
        self._attempted_prompts: dict[int, list[int]] = {}
        self._normalized: dict[int, dict[int, float]] = {}
        self._invalid_nodes: set[int] = set()

    def next_prompt(self, node_id: int) -> int | None:
        attempted = self._attempted_prompts.get(node_id, [])
        return PROMPT_IDS[len(attempted)] if len(attempted) < len(PROMPT_IDS) else None

    def observe_failure(self, node_id: int, prompt_id: int, turn: int) -> bool:
        """Record diagnostics without advancing a failed environment action."""
        self.failures.append({"node_id": node_id, "prompt_id": prompt_id, "turn": turn})
        return False

    def observe_success(
        self, node_id: int, prompt_id: int, turn: int, before: float, new_w: float,
    ) -> bool:
        """Record one successful public return and advance its probe sequence."""
        if (not isinstance(node_id, int) or isinstance(node_id, bool) or node_id <= 0
                or prompt_id not in PROMPT_IDS or turn not in TURN_MULTIPLIERS):
            self.censored.append({"node_id": node_id, "prompt_id": prompt_id,
                                  "turn": turn, "reason": "invalid_identity_or_turn"})
            return False
        expected_prompt = self.next_prompt(node_id)
        expected_turn = len(self._attempted_prompts.get(node_id, [])) + 1
        if prompt_id != expected_prompt or turn != expected_turn:
            self.censored.append({"node_id": node_id, "prompt_id": prompt_id,
                                  "turn": turn, "reason": "out_of_sequence"})
            self._invalid_nodes.add(node_id)
            return False
        self._attempted_prompts.setdefault(node_id, []).append(prompt_id)
        try:
            before, new_w = float(before), float(new_w)
        except (TypeError, ValueError):
            before = new_w = math.nan
        record: dict[str, object] = {
            "node_id": node_id, "prompt_id": prompt_id, "turn": turn,
            "before": before, "new_w": new_w,
        }
        if not math.isfinite(before) or not math.isfinite(new_w):
            record["reason"] = "nonfinite_or_non_numeric"
            self.censored.append(record)
            self._invalid_nodes.add(node_id)
            return False
        if before < -100.0 or before > 100.0 or abs(new_w) >= 100.0 - 1e-12:
            record["reason"] = "opinion_bound"
            self.censored.append(record)
            self._invalid_nodes.add(node_id)
            return False
        delta = new_w - before
        normalized = delta / TURN_MULTIPLIERS[turn]
        record.update({"delta": delta, "normalized_response": normalized})
        self._normalized.setdefault(node_id, {})[prompt_id] = normalized
        self.accepted.append(record)
        return True

    def node_rankings(self) -> Mapping[int, tuple[int, ...]]:
        rankings = {}
        for node_id, values in self._normalized.items():
            if node_id in self._invalid_nodes or set(values) != set(PROMPT_IDS):
                continue
            ordered = sorted(PROMPT_IDS, key=lambda prompt_id: (-values[prompt_id], prompt_id))
            rankings[node_id] = tuple(ordered)
        return rankings

    def node_best_prompt_ids(self) -> Mapping[int, tuple[int, ...]]:
        result = {}
        for node_id, ranking in self.node_rankings().items():
            values = self._normalized[node_id]
            best = values[ranking[0]]
            result[node_id] = tuple(
                prompt_id for prompt_id in PROMPT_IDS
                if abs(values[prompt_id] - best) <= self.tie_tolerance
            )
        return result

    def _informative_best_sets(self) -> list[set[int]]:
        result = []
        for node_id, best_ids in self.node_best_prompt_ids().items():
            values = self._normalized[node_id].values()
            if max(values) - min(values) > self.tie_tolerance:
                result.append(set(best_ids))
        return result

    @property
    def provisional_prompt_ids(self) -> tuple[int, ...]:
        """Return prompt IDs not contradicted by any informative probe node."""
        sets = self._informative_best_sets()
        if not sets:
            return ()
        common = set.intersection(*sets)
        return tuple(sorted(common))

    @property
    def calibrated_prompt_ids(self) -> tuple[int, ...]:
        sets = self._informative_best_sets()
        if len(sets) < self.required_complete_nodes:
            return ()
        common = set.intersection(*sets)
        return tuple(sorted(common))

    @property
    def calibrated_prompt_id(self) -> int | None:
        prompt_ids = self.calibrated_prompt_ids
        return prompt_ids[0] if prompt_ids else None

    @property
    def confident(self) -> bool:
        return self.calibrated_prompt_id is not None

    @property
    def calibration_complete(self) -> bool:
        return len(self.node_rankings()) >= self.required_complete_nodes

    def best_or_default(self) -> int:
        prompt_ids = self.calibrated_prompt_ids or self.provisional_prompt_ids
        return prompt_ids[0] if prompt_ids else self.default_prompt_id

    def normalized_values(self) -> dict[int, dict[int, float]]:
        return {node_id: dict(values) for node_id, values in self._normalized.items()}


__all__ = [
    "PROMPT_IDS", "TURN_MULTIPLIERS", "PromptCalibrationLedger",
    "select_prompt_probe_nodes",
]

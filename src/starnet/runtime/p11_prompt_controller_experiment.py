"""Development-only runtime that learns hidden prompt ordering from public returns."""

from __future__ import annotations

import math
import statistics

from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.candidates import Candidate
from starnet.policy.config import PolicyMode
from starnet.policy.prompt_calibration_experiment import (
    PromptCalibrationLedger,
    select_prompt_probe_nodes,
)
from starnet.policy.structural import ExperimentalPublicGreedyPlanner
from starnet.runtime.p8_controller import P8RuntimeController


class PromptLearningRuntimeController(P8RuntimeController):
    """Probe hidden prompt IDs, then plan with only learned public magnitudes."""

    def __init__(
        self,
        *args,
        prompt_ledger=None,
        max_probe_budget=12.0,
        max_probe_nodes=2,
        require_stage_envelope=False,
        **kwargs,
    ):
        kwargs.setdefault("p8_mode", "conservative")
        super().__init__(
            *args, require_stage_envelope=require_stage_envelope, **kwargs,
        )
        if (not math.isfinite(max_probe_budget) or not 0.0 <= max_probe_budget <= 12.0
                or isinstance(max_probe_nodes, bool) or not 1 <= max_probe_nodes <= 2
                or self.config.policy_mode is not PolicyMode.PUBLIC_GREEDY):
            raise ValueError("invalid P11 prompt-learning configuration")
        self.p11_experiment_mode = "prompt_learning"
        self.p11_max_probe_budget = float(max_probe_budget)
        self.p11_max_probe_nodes = int(max_probe_nodes)
        self.p11_prompt_ledger = prompt_ledger or PromptCalibrationLedger()
        self.p11_enabled = self.p8_mode is not None and (
            not require_stage_envelope or (
                self.node_count == 50 and self.initial_budget == 100.0
            )
        )
        self.p11_probe_nodes: tuple[int, ...] = ()
        self.p11_probe_node_index = 0
        self.p11_current_probe: tuple[int, int, int] | None = None
        self.p11_probe_attempts = 0
        self.p11_probe_successes = 0
        self.p11_probe_failures = 0
        self.p11_probe_budget = 0.0
        self.p11_calibration_finished = False
        self.p11_selected_prompt_id: int | None = None
        self.p11_selected_prompt_prior: float | None = None
        self.p11_selected_prompt_probe_values: tuple[float, ...] = ()
        self.p11_selected_prompt_observations: dict[int, float] = {}
        self.p11_selected_response_censored: list[dict[str, object]] = []
        self.p11_prompt_positive = False
        self.p11_fallback_to_p9 = False
        self.p11_response_switches = 0
        self.p11_errors = 0
        self.p11_planning_errors = 0
        self.p11_last_error: str | None = None
        self.p11_selected_prompt_dispatches = 0

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        if (not self.p11_enabled
                or (self.require_stage_envelope and self.blackboard.nonexistent_ids)
                or len(self.blackboard.scanned_ids) != self.node_count):
            super()._refresh_candidates(budget, phase)
            return
        if not self.p11_probe_nodes and not self.p11_calibration_finished:
            self.p11_probe_nodes = select_prompt_probe_nodes(
                self.blackboard,
                max_probe_budget=self.p11_max_probe_budget,
                max_nodes=self.p11_max_probe_nodes,
            )
            if not self.p11_probe_nodes:
                self._finish_calibration(use_learned=False)
        if not self.p11_calibration_finished:
            if self._refresh_probe_candidate(budget):
                return
            self._finish_calibration(use_learned=False)
        if self.p11_fallback_to_p9:
            super()._refresh_candidates(budget, phase)
            return
        try:
            self._refresh_learned_candidates(budget)
        except Exception as exc:
            self.p11_errors += 1
            self.p11_planning_errors += 1
            self.p11_last_error = type(exc).__name__
            self.p11_fallback_to_p9 = True
            super()._refresh_candidates(budget, phase)

    def _refresh_probe_candidate(self, budget: float) -> bool:
        while self.p11_probe_node_index < len(self.p11_probe_nodes):
            node_id = self.p11_probe_nodes[self.p11_probe_node_index]
            node = self.blackboard.nodes.get(node_id)
            prompt_id = self.p11_prompt_ledger.next_prompt(node_id)
            if node is None or node.comm_left is None or prompt_id is None:
                self.p11_probe_node_index += 1
                continue
            turn = 4 - node.comm_left
            action = Action("comm", node_id, prompt_id=prompt_id)
            if (turn not in (1, 2, 3)
                    or self.p11_probe_budget + action_cost(action) > self.p11_max_probe_budget
                    or not is_legal_action(action, self.blackboard, budget)
                    or action in self.failed_actions):
                self.p11_probe_node_index += 1
                continue
            identity = f"p11-probe:{node_id}:{prompt_id}:{turn}"
            self.effective_policy_mode = PolicyMode.PUBLIC_GREEDY
            self.analysis = self.analyst.analyze(self.blackboard)
            self.candidates = {
                identity: Candidate(
                    identity, action, 0, 0.0, 0.0,
                    "P11 public prompt calibration probe; compare returned opinion change "
                    "after the published turn multiplier; this candidate is legal and budget bounded",
                    (identity,),
                )
            }
            self.p8_options = False
            self.p11_current_probe = (node_id, prompt_id, turn)
            return True
        return False

    def _advance_probe_node(self) -> None:
        self.p11_probe_node_index += 1
        self.p11_current_probe = None

    def _probe_node_has_usable_evidence(self, node_id: int) -> bool:
        if self.p11_prompt_ledger.provisional_prompt_ids:
            return True
        values = self.p11_prompt_ledger.normalized_values().get(node_id, {})
        if len(values) != 3:
            return False
        ordered = tuple(float(values[prompt_id]) for prompt_id in (1, 2, 3))
        return (
            all(math.isfinite(value) for value in ordered)
            and max(ordered) - min(ordered) <= self.p11_prompt_ledger.tie_tolerance
            and abs(statistics.fmean(ordered)) > self.p11_prompt_ledger.tie_tolerance
        )

    def _finish_calibration(self, *, use_learned: bool) -> None:
        self.p11_calibration_finished = True
        self.p11_current_probe = None
        if not use_learned:
            self.p11_fallback_to_p9 = True
            return
        prompt_id = self.p11_prompt_ledger.best_or_default()
        values = self.p11_prompt_ledger.normalized_values()
        rankings = self.p11_prompt_ledger.node_rankings()
        selected = [
            float(values[node_id][prompt_id])
            for node_id in rankings
            if prompt_id in values.get(node_id, {})
        ]
        if not selected or any(not math.isfinite(value) for value in selected):
            self.p11_fallback_to_p9 = True
            return
        self.p11_selected_prompt_id = prompt_id
        self.p11_selected_prompt_probe_values = tuple(selected)
        self.p11_selected_prompt_prior = statistics.fmean(selected)
        self.p11_prompt_positive = self.p11_selected_prompt_prior > 0.0

    def _current_selected_prompt_prior(self) -> float:
        values = (
            *self.p11_selected_prompt_probe_values,
            *self.p11_selected_prompt_observations.values(),
        )
        if not values:
            raise ValueError("missing selected-prompt public response")
        prior = statistics.fmean(values)
        if not math.isfinite(prior):
            raise ValueError("nonfinite selected-prompt public response")
        self.p11_selected_prompt_prior = prior
        self.p11_prompt_positive = prior > 0.0
        return prior

    def _refresh_learned_candidates(self, budget: float) -> None:
        prompt_id = self.p11_selected_prompt_id
        if prompt_id is None:
            raise ValueError("missing learned prompt response")
        prior = self._current_selected_prompt_prior()

        def response(node_id, _node, turn):
            first = self.p11_selected_prompt_observations.get(node_id, prior)
            first = float(first)
            if not math.isfinite(first):
                raise ValueError("nonfinite learned response")
            return first * (0.5 ** (turn - 1))

        self.effective_policy_mode = PolicyMode.PUBLIC_GREEDY
        self.analysis = self.analyst.analyze(self.blackboard)
        planner = ExperimentalPublicGreedyPlanner(
            response,
            candidate_limit=len(self.blackboard.edges) + 2 * len(self.blackboard.nodes) + 1,
            conservative_structure=True,
            min_observed_responses=0,
            structure_roi_margin=1.0,
            defer_comm_if_shieldable=self.config.enable_public_comm_shield_guard,
        )
        structure_failures = {
            item for item in self.failed_actions
            if not (isinstance(item, Action) and item.kind == "comm")
            and not (isinstance(item, str)
                     and (item.startswith("comm:") or item.startswith("p11-probe:")))
        }
        generated = planner.candidates(
            self.blackboard, budget, structure_failures,
            observed_response_count=len(self.response_estimates),
        )
        candidates = {}
        for item in generated:
            if item.action.kind != "comm":
                candidates[item.candidate_id] = item
                continue
            action = Action("comm", item.action.target_node_1, prompt_id=prompt_id)
            if action in self.failed_actions or not is_legal_action(
                    action, self.blackboard, budget):
                continue
            turn = 4 - int(self.blackboard.nodes[action.target_node_1].comm_left or 0)
            identity = f"comm:{action.target_node_1}:{turn}:prompt:{prompt_id}"
            candidates[identity] = Candidate(
                identity, action, item.priority, item.score, item.roi,
                f"P11 learned prompt {prompt_id}; public first-slot prior={prior:.6f}; "
                + item.reason,
                (f"public-score:{identity}", f"p11-prompt:{prompt_id}"),
            )
        limit = max(24, self.config.structure_candidate_limit)
        self.candidates = dict(list(candidates.items())[:limit])
        self.structural_planner = None
        self.structural_plans = {}
        self.p8_options = False
        self.p11_response_switches += 1

    def _attempt_action(self, action: Action, candidate_id: str, budget: float) -> bool:
        expected = self.p11_current_probe
        node = self.blackboard.nodes.get(action.target_node_1)
        before = node.w if node is not None and action.kind == "comm" else None
        turn = (
            4 - int(node.comm_left or 0)
            if node is not None and action.kind == "comm" else None
        )
        selected_observation = bool(
            expected is None
            and self.p11_calibration_finished
            and not self.p11_fallback_to_p9
            and action.kind == "comm"
            and action.prompt_id == self.p11_selected_prompt_id
            and action.target_node_1 not in self.p11_selected_prompt_observations
        )
        response_missing = object()
        old_p9_response = self.response_estimates.get(
            action.target_node_1, response_missing,
        )
        if selected_observation:
            self.p11_selected_prompt_dispatches += 1
        success = super()._attempt_action(action, candidate_id, budget)
        if action.kind == "comm" and action.prompt_id != 1:
            if old_p9_response is response_missing:
                self.response_estimates.pop(action.target_node_1, None)
            else:
                self.response_estimates[action.target_node_1] = old_p9_response
        if expected is None:
            if selected_observation and success and before is not None and turn in (1, 2, 3):
                current = self.blackboard.nodes.get(action.target_node_1)
                if current is not None:
                    record = {
                        "node_id": action.target_node_1, "prompt_id": action.prompt_id,
                        "turn": turn, "before": before, "new_w": current.w,
                    }
                    if (before < -100.0 or before > 100.0
                            or abs(current.w) >= 100.0 - 1e-12):
                        record["reason"] = "opinion_bound"
                        self.p11_selected_response_censored.append(record)
                    else:
                        normalized = (current.w - before) / (0.5 ** (turn - 1))
                        if math.isfinite(normalized):
                            self.p11_selected_prompt_observations[action.target_node_1] = normalized
                            self._current_selected_prompt_prior()
                        else:
                            record["reason"] = "nonfinite_response"
                            self.p11_selected_response_censored.append(record)
            return success
        node_id, prompt_id, turn = expected
        if action != Action("comm", node_id, prompt_id=prompt_id):
            self.p11_errors += 1
            self.p11_last_error = "probe_action_mismatch"
            self._advance_probe_node()
            return success
        self.p11_probe_attempts += 1
        if not success:
            self.p11_probe_failures += 1
            self.p11_prompt_ledger.observe_failure(node_id, prompt_id, turn)
            self._advance_probe_node()
            return False
        self.p11_probe_successes += 1
        self.p11_probe_budget += action_cost(action)
        current = self.blackboard.nodes.get(node_id)
        accepted = bool(
            before is not None and current is not None
            and self.p11_prompt_ledger.observe_success(
                node_id, prompt_id, turn, before, current.w,
            )
        )
        self.p11_current_probe = None
        if not accepted:
            self._advance_probe_node()
        elif self.p11_prompt_ledger.next_prompt(node_id) is None:
            if self._probe_node_has_usable_evidence(node_id):
                self._finish_calibration(use_learned=True)
            else:
                self._advance_probe_node()
                if self.p11_probe_node_index >= len(self.p11_probe_nodes):
                    self._finish_calibration(use_learned=False)
        return True


__all__ = ["PromptLearningRuntimeController"]

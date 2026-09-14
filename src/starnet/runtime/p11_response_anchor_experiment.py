"""Development-only selected-prompt response anchor for frozen P11."""

from __future__ import annotations

import math
import statistics

from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.baseline import _public_influence_coefficients
from starnet.policy.candidates import Candidate
from starnet.policy.config import PolicyMode
from starnet.runtime.p11_prompt_controller_experiment import PromptLearningRuntimeController


class AnchoredPromptLearningController(PromptLearningRuntimeController):
    """Probe low-impact for ID, then sample selected ID on an influential node."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.p11_anchor_target: int | None = None
        self.p11_anchor_current: tuple[int, int] | None = None
        self.p11_anchor_finished = False
        self.p11_anchor_used = False
        self.p11_anchor_attempts = 0
        self.p11_anchor_successes = 0
        self.p11_anchor_failures = 0
        self.p11_anchor_censored = 0
        self.p11_anchor_budget = 0.0
        self.p11_anchor_population_prior: float | None = None
        self.p11_anchor_skip_reason: str | None = None

    def _anchor_candidate(self, budget: float) -> bool:
        prompt_id = self.p11_selected_prompt_id
        if prompt_id is None or not self.p11_prompt_positive:
            self.p11_anchor_skip_reason = "nonpositive_or_missing_prompt"
            return False
        influence = _public_influence_coefficients(self.blackboard)
        probe_nodes = set(self.p11_probe_nodes)
        eligible = [
            node_id for node_id, node in self.blackboard.nodes.items()
            if node_id not in probe_nodes
            and node.persona in {"和平", "中立"}
            and node.comm_left == 3
            and -60.0 < float(node.w) < 60.0
        ]
        eligible.sort(key=lambda node_id: (
            -influence.get(node_id, 0.0), abs(float(self.blackboard.nodes[node_id].w)),
            node_id,
        ))
        action = (
            Action("comm", eligible[0], prompt_id=prompt_id) if eligible else None
        )
        if action is None or not is_legal_action(action, self.blackboard, budget):
            self.p11_anchor_skip_reason = "no_legal_target"
            return False
        identity = f"p11-anchor:{action.target_node_1}:{prompt_id}"
        self.effective_policy_mode = PolicyMode.PUBLIC_GREEDY
        self.analysis = self.analyst.analyze(self.blackboard)
        self.candidates = {
            identity: Candidate(
                identity, action, 0, 0.0, 0.0,
                "P11 selected-prompt response anchor on the highest public component-"
                "influence eligible node; this legal action supplies a post-calibration "
                "first-equivalent magnitude for unknown-node planning",
                (identity,),
            )
        }
        self.p8_options = False
        self.p11_anchor_target = action.target_node_1
        self.p11_anchor_current = (action.target_node_1, prompt_id)
        return True

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        if (self.p11_calibration_finished and not self.p11_fallback_to_p9
                and not self.p11_anchor_finished):
            if self._anchor_candidate(budget):
                return
            self.p11_anchor_finished = True
        super()._refresh_candidates(budget, phase)

    def _current_selected_prompt_prior(self) -> float:
        if self.p11_anchor_used and self.p11_selected_prompt_observations:
            prior = statistics.fmean(
                float(value) for value in self.p11_selected_prompt_observations.values()
            )
            if not math.isfinite(prior):
                raise ValueError("nonfinite anchored selected-prompt prior")
            self.p11_selected_prompt_prior = prior
            self.p11_prompt_positive = prior > 0.0
            self.p11_anchor_population_prior = prior
            return prior
        return super()._current_selected_prompt_prior()

    def _attempt_action(self, action: Action, candidate_id: str, budget: float) -> bool:
        expected = self.p11_anchor_current
        success = super()._attempt_action(action, candidate_id, budget)
        if expected is None:
            return success
        node_id, prompt_id = expected
        self.p11_anchor_current = None
        self.p11_anchor_finished = True
        self.p11_anchor_attempts += 1
        if action != Action("comm", node_id, prompt_id=prompt_id):
            self.p11_anchor_failures += 1
            self.p11_anchor_skip_reason = "action_mismatch"
            return success
        if not success:
            self.p11_anchor_failures += 1
            self.p11_anchor_skip_reason = "action_failed"
            return False
        self.p11_anchor_budget += action_cost(action)
        if node_id not in self.p11_selected_prompt_observations:
            self.p11_anchor_censored += 1
            self.p11_anchor_skip_reason = "response_censored"
            return True
        self.p11_anchor_successes += 1
        self.p11_anchor_used = True
        self._current_selected_prompt_prior()
        return True


__all__ = ["AnchoredPromptLearningController"]

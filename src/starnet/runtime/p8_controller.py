"""Shared P8 executor; production activation is controlled by qualification."""

from __future__ import annotations

from starnet.policy.actions import action_cost, is_legal_action
from starnet.policy.candidates import Candidate
from starnet.policy.config import PolicyMode
from starnet.policy.p8_experiment import choose_p8_action, public_board_salt
from starnet.runtime.controller import RuntimeController


class P8RuntimeController(RuntimeController):
    """Keep the full production executor and quota guards in a local trial."""

    def __init__(self, *args, p8_mode="audited", require_stage_envelope=False, **kwargs):
        if p8_mode not in ("conservative", "audited"):
            raise ValueError("unsupported P8 trial mode")
        super().__init__(*args, **kwargs)
        self.require_stage_envelope = require_stage_envelope
        self.p8_mode = p8_mode if (not require_stage_envelope or (
            self.node_count == 50 and self.initial_budget == 100.0
        )) else None
        self.p8_salt = None
        self.p8_cache = {}
        self.p8_options = False
        self.p8_proposals = 0
        self.p8_planning_errors = 0

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        super()._refresh_candidates(budget, phase)
        self.p8_options = False
        if (self.p8_mode is None
                or (self.require_stage_envelope and self.blackboard.nonexistent_ids)
                or self.effective_policy_mode is not PolicyMode.PUBLIC_GREEDY
                or len(self.blackboard.scanned_ids) != self.node_count or not self.candidates):
            return
        try:
            if self.p8_salt is None:
                self.p8_salt = public_board_salt(self.blackboard)
            decision = choose_p8_action(
                self.blackboard, budget, self.response_estimates,
                remaining_steps=max(0, self._safe_step_limit - self.action_attempts),
                salt=self.p8_salt, mode=self.p8_mode, evaluation_cache=self.p8_cache,
            )
        except Exception:
            self.p8_planning_errors += 1
            return
        if not decision.deviated:
            return
        action = decision.action
        if action in self.failed_actions or not is_legal_action(action, self.blackboard, budget):
            return
        baseline = next((candidate for candidate in self.candidates.values()
                         if candidate.action == decision.baseline_action), None)
        if baseline is None:
            return
        identity = f"p8:{action.kind}:{action.target_node_1}:{action.target_node_2}:{self.blackboard.state_version}"
        gain = (min(decision.mean_delta, decision.audit_mean_delta)
                if self.p8_mode == "audited" else decision.mean_delta)
        # Values are continuation advantages relative to the baseline plan,
        # not immediate changes to the environment's score.
        proposed = Candidate(identity, action, 0, gain, gain / action_cost(action),
                             f"P8 assumed-response continuation advantage; selection mean={decision.mean_delta:.6f}; "
                             f"selection minimum={decision.minimum_delta:.6f}; mode={self.p8_mode}; "
                             f"additional audit scenarios={len(decision.audit_paired_deltas)}, audit mean={decision.audit_mean_delta:.6f}, minimum={decision.audit_minimum_delta:.6f}; "
                             "baseline alternative has relative advantage zero", (identity,))
        fallback = Candidate(baseline.candidate_id, baseline.action, 0, 0.0, 0.0,
                             "Current public_greedy baseline; relative continuation advantage zero",
                             baseline.evidence_ids)
        self.candidates = {proposed.candidate_id: proposed, fallback.candidate_id: fallback}
        self.p8_options = True
        self.p8_proposals += 1

    def _llm_candidate_options(self, candidates):
        return candidates if self.p8_options else super()._llm_candidate_options(candidates)


__all__ = ["P8RuntimeController"]

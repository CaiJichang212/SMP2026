"""Development-only controller for explicitly approved P10 structure prefixes."""

from __future__ import annotations

import hashlib
import statistics

from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.candidates import Candidate
from starnet.policy.config import PolicyMode
from starnet.policy.p10_structure_plan_experiment import (
    FullPlanDecision,
    FullStructurePlan,
    choose_full_plan,
    search_full_structure_plan,
)
from starnet.runtime.p8_controller import P8RuntimeController


def _action_name(action: Action) -> str:
    if action.kind == "cut":
        return f"cut:{action.target_node_1}-{action.target_node_2}"
    return f"{action.kind}:{action.target_node_1}"


class P10RuntimeController(P8RuntimeController):
    """Search once, then execute an LLM-approved prefix one action per step."""

    def __init__(self, *args, max_structures=12, beam_width=4, **kwargs):
        super().__init__(*args, **kwargs)
        if max_structures <= 0 or beam_width <= 0:
            raise ValueError("invalid P10 search bounds")
        self.p10_max_structures = max_structures
        self.p10_beam_width = beam_width
        self.p10_search_completed = False
        self.p10_searches = 0
        self.p10_planning_errors = 0
        self.p10_last_planning_error = None
        self.p10_options = False
        self.p10_plan_id = None
        self.p10_baseline_id = None
        self.p10_plan: FullStructurePlan | None = None
        self.p10_decision: FullPlanDecision | None = None
        self.p10_pending: list[Action] = []
        self.p10_approved_plans = 0
        self.p10_baseline_choices = 0
        self.p10_prefix_successes = 0
        self.p10_prefix_failures = 0
        self.p10_prefix_completed = 0

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        if self.p10_pending:
            action = self.p10_pending[0]
            if is_legal_action(action, self.blackboard, budget):
                identity = f"p10-prefix:{self.p10_prefix_successes}:{_action_name(action)}"
                self.analysis = self.analyst.analyze(self.blackboard)
                self.candidates = {
                    identity: Candidate(
                        identity, action, 0, 1.0, 1.0 / action_cost(action),
                        "Previously LLM-approved P10 structure prefix; execute this next validated action",
                        (identity,),
                    )
                }
                self.p10_options = False
                return
            self.p10_pending.clear()
            self.p10_prefix_failures += 1

        super()._refresh_candidates(budget, phase)
        self.p10_options = False
        if (self.p10_search_completed
                or self.effective_policy_mode is not PolicyMode.PUBLIC_GREEDY
                or len(self.blackboard.scanned_ids) != self.node_count
                or not self.candidates):
            return
        self.p10_search_completed = True
        self.p10_searches += 1
        try:
            if self.p8_salt is None:
                from starnet.policy.p8_experiment import public_board_salt
                self.p8_salt = public_board_salt(self.blackboard)
            plan = search_full_structure_plan(
                self.blackboard, budget, self.response_estimates,
                remaining_steps=max(0, self._safe_step_limit - self.action_attempts),
                max_structures=self.p10_max_structures,
                beam_width=self.p10_beam_width,
            )
            if plan is None:
                return
            decision = choose_full_plan(
                self.blackboard, budget, self.response_estimates,
                remaining_steps=max(0, self._safe_step_limit - self.action_attempts),
                salt=self.p8_salt, max_structures=self.p10_max_structures,
                beam_width=self.p10_beam_width, risk_mode="mean_audited",
                proposed_plan=plan,
            )
        except Exception as exc:
            self.p10_planning_errors += 1
            self.p10_last_planning_error = type(exc).__name__
            return
        self.p10_plan = plan
        self.p10_decision = decision
        if not decision.accepted:
            return
        baseline = next(
            (candidate for candidate in self.candidates.values()
             if candidate.action == decision.baseline_action),
            None,
        )
        if baseline is None or not plan.structure_actions:
            return
        sequence = ",".join(_action_name(action) for action in plan.structure_actions)
        material = "|".join(_action_name(action) for action in plan.structure_actions)
        identity = "p10-plan:" + hashlib.sha256(material.encode("ascii")).hexdigest()[:16]
        selection_mean = statistics.fmean(decision.selection_deltas)
        audit_mean = statistics.fmean(decision.audit_deltas)
        cost = sum(action_cost(action) for action in plan.structure_actions)
        proposed = Candidate(
            identity,
            plan.structure_actions[0],
            0,
            min(selection_mean, audit_mean),
            min(selection_mean, audit_mean) / cost,
            "P10 COMPLETE PREFIX APPROVAL: selecting this candidate ID authorizes every "
            f"listed structure action in order, one validated action per host step; sequence=[{sequence}]; "
            f"structure_cost={cost:.1f}; bounded-response assumptions: selection mean={selection_mean:.6f}, "
            f"minimum={min(decision.selection_deltas):.6f}; independent audit mean={audit_mean:.6f}, "
            f"minimum={min(decision.audit_deltas):.6f}; individual negative scenarios are permitted by "
            "the preregistered mean-audited development rule; after the prefix, P9 replans persuasion "
            "from actual public responses",
            (identity,),
        )
        fallback = Candidate(
            baseline.candidate_id, baseline.action, 0, 0.0, 0.0,
            "P9 bounded baseline; selecting this ID rejects the complete P10 prefix",
            baseline.evidence_ids,
        )
        self.p10_plan_id = identity
        self.p10_baseline_id = fallback.candidate_id
        self.candidates = {identity: proposed, fallback.candidate_id: fallback}
        self.p10_options = True
        # P10 supersedes the P8 two-option presentation for this one decision.
        self.p8_options = False

    def _llm_candidate_options(self, candidates):
        return candidates if self.p10_options else super()._llm_candidate_options(candidates)

    def _create_plan(self, budget: float) -> None:
        if self.p10_pending:
            candidate_id = next(iter(self.candidates), None)
            self.queue = [candidate_id] if candidate_id is not None else []
            self._last_step_selected_ids = list(self.queue)
            return
        if not self.p10_options:
            super()._create_plan(budget)
            return
        accepted_before = self.llm_accepted
        super()._create_plan(budget)
        selected = self.queue[0] if self.queue else None
        explicitly_approved = (
            self.llm_accepted > accepted_before and selected == self.p10_plan_id
        )
        if explicitly_approved and self.p10_plan is not None:
            self.p10_pending = list(self.p10_plan.structure_actions)
            self.p10_approved_plans += 1
        else:
            self.p10_baseline_choices += 1
            self.queue = [self.p10_baseline_id] if self.p10_baseline_id else []
            self._last_step_selected_ids = list(self.queue)
        self.p10_options = False

    def _execute_next(self, budget: float) -> int:
        prefix_active = bool(self.p10_pending)
        expected = self.p10_pending[0] if prefix_active else None
        result = super()._execute_next(budget)
        if prefix_active and self.last_action_attempted:
            if self.last_action_succeeded and expected == self._action_from_last_step():
                self.p10_pending.pop(0)
                self.p10_prefix_successes += 1
                if not self.p10_pending:
                    self.p10_prefix_completed += 1
            else:
                self.p10_pending.clear()
                self.p10_prefix_failures += 1
        return result

    def _action_from_last_step(self) -> Action | None:
        payload = self._last_step_action
        return Action(**payload) if isinstance(payload, dict) else None


__all__ = ["P10RuntimeController"]

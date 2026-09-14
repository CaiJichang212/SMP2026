"""Development-only controller for explicitly approved P10 structure prefixes."""

from __future__ import annotations

import hashlib
import statistics
from typing import Literal

from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.candidates import Candidate, select_deterministic_batch
from starnet.policy.config import PolicyMode
from starnet.policy.p10_structure_plan_experiment import (
    FullPlanDecision,
    FullStructurePlan,
    choose_full_plan,
    search_full_structure_plan,
)
from starnet.policy.p8_experiment import public_board_salt
from starnet.runtime.p8_controller import P8RuntimeController
from starnet.runtime.controller import MAX_BATCH_ACTIONS, RuntimeController
from starnet.policy.public_response_mixture import PublicResponseMixtureLedger
from starnet.policy.structural import ExperimentalPublicGreedyPlanner


P10ExperimentMode = Literal["plan_only", "response_only", "combined"]


def _p10_action_name(action: Action) -> str:
    if action.kind == "cut":
        return f"cut:{action.target_node_1}-{action.target_node_2}"
    return f"{action.kind}:{action.target_node_1}"


class P10RuntimeController(P8RuntimeController):
    """Search once, then execute an LLM-approved prefix one action per step."""

    def __init__(self, *args, max_structures=12, beam_width=4,
                 response_estimator=None, experiment_mode: P10ExperimentMode = "plan_only",
                 **kwargs):
        super().__init__(*args, **kwargs)
        if (max_structures <= 0 or beam_width <= 0
                or experiment_mode not in ("plan_only", "response_only", "combined")):
            raise ValueError("invalid P10 search bounds")
        self.p10_experiment_mode = experiment_mode
        self.p10_max_structures = max_structures
        self.p10_beam_width = beam_width
        self.p10_response_estimator = (
            response_estimator
            if response_estimator is not None or experiment_mode == "plan_only"
            else PublicResponseMixtureLedger()
        )
        self.p10_response_disabled = False
        self.p10_response_disable_reason = None
        self.p10_response_switches = 0
        self.p10_search_completed = False
        self.p10_searches = 0
        self.p10_planning_errors = 0
        self.p10_last_planning_error = None
        self.p10_options = False
        self.p10_plan_id = None
        self.p10_original_candidates: dict[str, Candidate] = {}
        self.p10_original_p8_options = False
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
                identity = f"p10-prefix:{self.p10_prefix_successes}:{_p10_action_name(action)}"
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

        if self._response_mode_enabled() and self._response_gate_open():
            if self._refresh_response_candidates(budget, phase):
                return

        super()._refresh_candidates(budget, phase)
        self.p10_options = False
        if not self._plan_mode_enabled() or self.p10_search_completed:
            return
        if len(self.blackboard.scanned_ids) != self.node_count:
            return
        # The single search opportunity is consumed at the first complete
        # public snapshot, even if P9 currently has no candidate. It is never
        # delayed to collect communications as implicit probes.
        self.p10_search_completed = True
        if (self.effective_policy_mode is not PolicyMode.PUBLIC_GREEDY
                or not self.candidates):
            return
        self.p10_searches += 1
        try:
            if self.p8_salt is None:
                self.p8_salt = public_board_salt(self.blackboard)
            plan = search_full_structure_plan(
                self.blackboard, budget, self.response_estimates,
                remaining_steps=max(0, self._safe_step_limit - self.action_attempts),
                max_structures=self.p10_max_structures,
                beam_width=self.p10_beam_width,
                response_estimator=self._p10_response_fn(),
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
        if not plan.structure_actions:
            return
        self.p10_original_candidates = dict(self.candidates)
        self.p10_original_p8_options = self.p8_options
        sequence = ",".join(_p10_action_name(action) for action in plan.structure_actions)
        material = "|".join(_p10_action_name(action) for action in plan.structure_actions)
        identity = "p10-plan:" + hashlib.sha256(material.encode("ascii")).hexdigest()[:16]
        selection_mean = statistics.fmean(decision.selection_deltas)
        audit_mean = statistics.fmean(decision.audit_deltas)
        cost = sum(action_cost(action) for action in plan.structure_actions)
        proposed = Candidate(
            identity,
            plan.structure_actions[0],
            0,
            min(selection_mean, audit_mean),
            min(selection_mean, audit_mean) / max(budget, 0.5),
            "P10 COMPLETE PREFIX APPROVAL: selecting this candidate ID authorizes every "
            f"listed structure action in order, one validated action per host step; sequence=[{sequence}]; "
            f"structure_cost={cost:.1f}; equal-resource terminal comparison uses current total "
            f"budget={budget:.1f}; bounded-response assumptions: selection mean={selection_mean:.6f}, "
            f"minimum={min(decision.selection_deltas):.6f}; independent audit mean={audit_mean:.6f}, "
            f"minimum={min(decision.audit_deltas):.6f}; individual negative scenarios are permitted by "
            "the preregistered mean-audited development rule; all continuation gains use the public-greedy "
            "reference (PG=0), not an assumption that P9 gain is zero; after the prefix, P9 replans "
            "persuasion from actual public responses",
            (identity,),
        )
        self.p10_plan_id = identity
        display = {}
        for candidate_id, candidate in self.p10_original_candidates.items():
            if candidate.action == decision.baseline_action:
                display[candidate_id] = Candidate(
                    candidate_id, candidate.action, candidate.priority, 0.0, 0.0,
                    "PG REFERENCE: equal-resource public-greedy continuation gain=0; "
                    + candidate.reason,
                    candidate.evidence_ids,
                )
            elif self.p10_original_p8_options and candidate_id.startswith("p8:"):
                display[candidate_id] = Candidate(
                    candidate_id, candidate.action, candidate.priority,
                    candidate.score, candidate.score / max(budget, 0.5),
                    "P8 equal-resource terminal continuation gain relative to PG; "
                    + candidate.reason,
                    candidate.evidence_ids,
                )
            else:
                display[candidate_id] = Candidate(
                    candidate_id, candidate.action, candidate.priority,
                    candidate.score, candidate.roi,
                    "P9 ORIGINAL IMMEDIATE candidate; score is not numerically comparable "
                    "to terminal continuation gains; " + candidate.reason,
                    candidate.evidence_ids,
                )
        self.candidates = {identity: proposed, **display}
        self.p10_options = True
        # RuntimeController creates one combined LLM request. P8's specialized
        # accounting is reproduced after the selected original ID is known.
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
        RuntimeController._create_plan(self, budget)
        selected = self.queue[0] if self.queue else None
        llm_accepted = self.llm_accepted > accepted_before
        explicitly_approved = llm_accepted and selected == self.p10_plan_id
        if explicitly_approved and self.p10_plan is not None:
            self.p10_pending = list(self.p10_plan.structure_actions)
            self.p10_approved_plans += 1
        elif llm_accepted and selected in self.p10_original_candidates:
            self.p10_baseline_choices += 1
            self.candidates = dict(self.p10_original_candidates)
            if selected.startswith("p8:"):
                self.p8_selected_proposals += 1
            elif self.p10_original_p8_options:
                self.p8_selected_baseline += 1
        else:
            # Reconstruct P9's deterministic fallback on the original option
            # set. The P10 plan must never enter an invalid-output fallback.
            original = list(self.p10_original_candidates.values())
            options = (
                original if self.p10_original_p8_options
                else RuntimeController._llm_candidate_options(self, original)
            )
            requested = select_deterministic_batch(
                options, budget, MAX_BATCH_ACTIONS, config=self.config,
            )[:1]
            validation = self._valid_queue(requested, budget)
            self.candidates = dict(self.p10_original_candidates)
            self.queue = list(validation.candidate_ids)
            self._last_step_selected_ids = list(self.queue)
            self.p10_baseline_choices += 1
        self.p10_options = False
        self.p8_options = False

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

    def _p10_response_fn(self):
        estimator = self.p10_response_estimator
        if estimator is None or not self._response_gate_open():
            return None
        predict = getattr(estimator, "predict", None)
        if not callable(predict):
            raise ValueError("P10 response estimator must expose predict")
        def estimate(node_id, node, turn):
            try:
                return predict(
                    node_id, node.persona, turn, self.response_estimates, gated=True,
                )
            except Exception as exc:
                self._disable_response(type(exc).__name__)
                raise
        return estimate

    def _plan_mode_enabled(self) -> bool:
        return (
            self.p10_experiment_mode in ("plan_only", "combined")
            and self._p10_envelope_open()
        )

    def _response_mode_enabled(self) -> bool:
        return (
            self.p10_experiment_mode in ("response_only", "combined")
            and self.p10_response_estimator is not None
            and not self.p10_response_disabled
            and self._p10_envelope_open()
        )

    def _p10_envelope_open(self) -> bool:
        return (
            self.p8_mode is not None
            and not (self.require_stage_envelope and self.blackboard.nonexistent_ids)
        )

    def _disable_response(self, reason: str) -> None:
        self.p10_response_disabled = True
        self.p10_response_disable_reason = reason

    def _response_gate_open(self) -> bool:
        if not self._response_mode_enabled():
            return False
        try:
            return bool(self.p10_response_estimator.gate_open())
        except Exception as exc:
            self._disable_response(type(exc).__name__)
            return False

    def _refresh_response_candidates(self, budget: float, phase: str) -> bool:
        try:
            response_fn = self._p10_response_fn()
            if response_fn is None:
                return False
            self.effective_policy_mode = PolicyMode.PUBLIC_GREEDY
            self.analysis = self.analyst.analyze(self.blackboard)
            planner = ExperimentalPublicGreedyPlanner(
                response_fn,
                candidate_limit=max(24, self.config.structure_candidate_limit),
                min_observed_responses=0,
                structure_roi_margin=1.0,
                defer_comm_if_shieldable=self.config.enable_public_comm_shield_guard,
            )
            candidates = planner.candidates(
                self.blackboard, budget, self.failed_actions,
                observed_response_count=len(self.response_estimates),
            )
        except Exception as exc:
            self._disable_response(type(exc).__name__)
            return False
        self.candidates = {candidate.candidate_id: candidate for candidate in candidates}
        self.structural_planner = None
        self.structural_plans = {}
        self.p8_options = False
        self.p10_options = False
        self.p10_response_switches += 1
        return True

    def _attempt_action(self, action: Action, candidate_id: str, budget: float) -> bool:
        node = self.blackboard.nodes.get(action.target_node_1)
        before = node.w if action.kind == "comm" and node is not None else None
        persona = node.persona if node is not None else None
        first_turn = bool(action.kind == "comm" and node is not None and node.comm_left == 3)
        success = super()._attempt_action(action, candidate_id, budget)
        observe = getattr(self.p10_response_estimator, "observe_first", None)
        current = self.blackboard.nodes.get(action.target_node_1)
        if (success and first_turn and callable(observe) and before is not None
                and persona is not None and current is not None):
            try:
                observe(persona, before, current.w)
            except Exception as exc:
                self._disable_response(type(exc).__name__)
        return success

    def _action_from_last_step(self) -> Action | None:
        payload = self._last_step_action
        return Action(**payload) if isinstance(payload, dict) else None


__all__ = ["P10ExperimentMode", "P10RuntimeController"]

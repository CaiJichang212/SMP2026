"""Deterministic scan, analysis, and batch execution state machine.

The controller is independent of ``casevo``. A local caller may attach a
``RuntimeTrace`` after constructing its model and before the first ``step``;
without that explicit injection all trace paths are inert.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.candidates import (
    Candidate,
    generate_candidates,
    parse_llm_batch_detailed,
    select_deterministic_batch,
)
from starnet.policy.graph_analysis import GraphAnalysis, analyze_graph
from starnet.policy.config import DEFAULT_POLICY_CONFIG, PolicyConfig
from starnet.policy.config import PolicyMode
from starnet.policy.calibration import CalibrationProfile, DEFAULT_CALIBRATION_PROFILE
from starnet.policy.cmg import (
    CMGPlanningError,
    ResponseLedger,
    ScoredCandidate,
    choose_cmg_action,
)
from starnet.runtime.env_adapter import ActionOutcome, StarNetEnvironment, apply_action_outcome
from starnet.runtime.trace import NullRuntimeTrace, RuntimeTrace, safe_error


MAX_LLM_CALLS = 3
MAX_BATCH_ACTIONS = 10
MAX_CONSECUTIVE_INVALID = 3


class ControllerState(str, Enum):
    """Explicit controller state, observable by the submission host."""

    INIT = "INIT"
    SCAN_ALL = "SCAN_ALL"
    ANALYZE = "ANALYZE"
    PLAN_BATCH = "PLAN_BATCH"
    PLAN_CMG = "PLAN_CMG"
    EXECUTE = "EXECUTE"
    REANALYZE = "REANALYZE"
    STOP = "STOP"


class StopReason(str, Enum):
    """De-identified reasons for normal controller termination."""

    NO_CANDIDATES = "no_candidates"
    INSUFFICIENT_BUDGET = "insufficient_budget"
    NO_VALID_ACTIONS = "no_valid_actions"
    STATE_GUARD = "state_guard"
    STEP_LIMIT = "step_limit"
    RUNNER_ERROR = "runner_error"
    NO_POSITIVE_GAIN = "no_positive_gain"


def infer_node_count(initial_budget: float) -> int:
    """Infer the competition network tier from the public starting budget."""
    return 100 if initial_budget >= 150.0 else 50


class DeterministicScout:
    """Scan fixed node IDs in order and never call an LLM."""

    def __init__(self, node_count: int) -> None:
        if node_count <= 0:
            raise ValueError("node_count 必须为正整数")
        self.node_count = node_count
        self._next_node_id = 1

    @property
    def exhausted(self) -> bool:
        return self._next_node_id > self.node_count

    def next_action(self, blackboard: Blackboard) -> Action | None:
        """Return the next unknown ID scan; known IDs are not requested again."""
        while self._next_node_id <= self.node_count:
            node_id = self._next_node_id
            self._next_node_id += 1
            if blackboard.can_scan(node_id):
                return Action("scan", node_id)
        return None


class GraphAnalyst:
    """Thin role wrapper retained for a clear single-file submission boundary."""

    def analyze(self, blackboard: Blackboard) -> GraphAnalysis:
        return analyze_graph(blackboard)

    def generate_candidates(
        self,
        analysis: GraphAnalysis,
        blackboard: Blackboard,
        budget: float,
        failed_actions: set[str],
        config: PolicyConfig,
    ) -> list[Candidate]:
        return generate_candidates(analysis, blackboard, budget, failed_actions, config)


LlmRanker = Callable[[dict[str, Any]], object]


@dataclass(frozen=True)
class BatchPlan:
    """A candidate queue plus the exact source of its ordering."""

    candidate_ids: tuple[str, ...]
    source: str
    fallback_reason: str | None = None
    request_payload: Mapping[str, Any] | None = None
    raw_response: object | None = None
    parsed_candidate_ids: tuple[str, ...] = ()
    error: Mapping[str, str] | None = None

    @property
    def used_llm(self) -> bool:
        """Compatibility alias for the prior two-state plan API."""
        return self.source == "llm"


@dataclass(frozen=True)
class QueueValidation:
    candidate_ids: tuple[str, ...]
    discarded: tuple[dict[str, str], ...]


class BatchCommander:
    """Use an LLM only to order Python-validated candidates, with fallback."""

    def __init__(
        self,
        llm_ranker: LlmRanker | None = None,
        *,
        config: PolicyConfig = DEFAULT_POLICY_CONFIG,
        contest_llm_limit: int | None = None,
    ) -> None:
        self.llm_ranker = llm_ranker
        self.config = config
        self.max_llm_calls = min(
            config.max_llm_calls,
            contest_llm_limit if contest_llm_limit is not None else config.max_llm_calls,
        )
        self.llm_calls = 0

    @property
    def can_request_llm(self) -> bool:
        return self.llm_ranker is not None and self.llm_calls < self.max_llm_calls

    def preview_payload(
        self,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
    ) -> dict[str, Any]:
        """Build the exact payload for the next request without consuming quota."""
        return self._build_payload(candidates, budget, analysis, self.llm_calls + 1)

    def plan(
        self,
        *,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
        request_payload: Mapping[str, Any] | None = None,
    ) -> BatchPlan:
        candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
        fallback = tuple(select_deterministic_batch(candidates, budget, MAX_BATCH_ACTIONS, config=self.config))
        if not candidate_map:
            return BatchPlan(fallback, "deterministic_fallback", "no_candidates")
        if self.llm_ranker is None:
            return BatchPlan(fallback, "deterministic_fallback", "no_llm_ranker")
        if self.llm_calls >= self.max_llm_calls:
            return BatchPlan(fallback, "quota_exhausted", "quota_exhausted")

        # Quota is consumed before the external call, including a timeout.
        self.llm_calls += 1
        payload = dict(request_payload or self._build_payload(candidates, budget, analysis, self.llm_calls))
        try:
            raw_response = self.llm_ranker(payload)
        except Exception as exc:
            return BatchPlan(
                fallback,
                "deterministic_fallback",
                "exception",
                payload,
                error=safe_error(exc),
            )

        parsed = parse_llm_batch_detailed(raw_response, candidate_map, budget, config=self.config)
        if parsed.accepted:
            return BatchPlan(
                parsed.candidate_ids,
                "llm",
                request_payload=payload,
                raw_response=raw_response,
                parsed_candidate_ids=parsed.candidate_ids,
            )
        return BatchPlan(
            parsed.candidate_ids,
            "deterministic_fallback",
            parsed.fallback_reason,
            payload,
            raw_response,
            parsed.candidate_ids,
        )

    def _build_payload(
        self,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
        llm_call_number: int,
    ) -> dict[str, Any]:
        graph = analysis.graph
        negative_nodes = sorted(
            node_id
            for node_id, metrics in analysis.node_metrics.items()
            if metrics.danger > 0
        )
        positive_nodes = sorted(
            node_id
            for node_id, metrics in analysis.node_metrics.items()
            if metrics.positive_influence > 0
        )
        return {
            "stage": ControllerState.PLAN_BATCH.value,
            "budget": budget,
            "llm_calls": llm_call_number,
            "graph": {
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(),
                "community_count": analysis.community_count,
                "negative_nodes": negative_nodes,
                "positive_nodes": positive_nodes,
            },
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "action": asdict(candidate.action),
                    "cost": action_cost(candidate.action),
                    "priority": candidate.priority,
                    "score": candidate.score,
                    "roi": candidate.roi,
                    "reason": candidate.reason,
                }
                for candidate in candidates
            ],
        }


class RuntimeController:
    """V0 state machine plus fail-closed V1 CMG; one public action per step."""

    def __init__(
        self,
        env: StarNetEnvironment,
        llm_ranker: LlmRanker | None = None,
        *,
        initial_budget: float | None = None,
        node_count: int | None = None,
        blackboard: Blackboard | None = None,
        config: PolicyConfig = DEFAULT_POLICY_CONFIG,
        calibration_profile: CalibrationProfile = DEFAULT_CALIBRATION_PROFILE,
    ) -> None:
        self.env = env
        self.blackboard = blackboard if blackboard is not None else Blackboard()
        self.initial_budget = float(
            env.get_remaining_budget() if initial_budget is None else initial_budget
        )
        self.node_count = infer_node_count(self.initial_budget) if node_count is None else node_count
        self.config = config
        self.calibration_profile = calibration_profile
        self.policy_mode = config.policy_mode
        self.response_ledger = ResponseLedger()
        self.cmg_candidate: ScoredCandidate | None = None
        self.cmg_fallback_reason: str | None = None
        self.scout = DeterministicScout(self.node_count)
        self.analyst = GraphAnalyst()
        # The experiment may forbid LLM use even when the official model has a ranker.
        self.commander = BatchCommander(
            llm_ranker if config.max_llm_calls else None,
            config=config,
            contest_llm_limit=config.contest_llm_limit(self.node_count),
        )
        self.state = ControllerState.INIT
        self.analysis: GraphAnalysis | None = None
        self.candidates: dict[str, Candidate] = {}
        self.queue: list[str] = []
        self.failed_actions: set[str] = set()
        self.consecutive_invalid = 0
        self.last_action_attempted = False
        self.last_action_succeeded: bool | None = None
        self.last_action_error: str | None = None
        self.action_attempts = 0
        self.action_successes = 0
        self.action_failures = 0
        self.stop_reason: StopReason | None = None
        self._trace: RuntimeTrace = NullRuntimeTrace()
        self._step_number = 0
        self._last_trace_budget_after: float | None = None
        self._last_step_action: dict[str, Any] | None = None
        self._last_step_action_result = "idle"
        self._last_step_selected_ids: list[str] = []

    @property
    def llm_calls(self) -> int:
        return self.commander.llm_calls

    @property
    def stopped(self) -> bool:
        return self.state is ControllerState.STOP

    @property
    def step_number(self) -> int:
        return self._step_number

    def attach_trace(self, trace: RuntimeTrace) -> None:
        """Attach optional local diagnostics before the first controller step."""
        self._trace = trace
        self._emit(
            "run.started",
            self.initial_budget,
            self.initial_budget,
            {
                "node_count": self.scout.node_count,
                "initial_budget": self.initial_budget,
                "max_llm_calls": self.commander.max_llm_calls,
                "safety_step_limit": self.config.safety_step_limit(self.node_count),
                "max_batch_actions": MAX_BATCH_ACTIONS,
                "policy_mode": self.policy_mode.value,
                "calibration_profile_hash": self.calibration_profile.profile_hash or None,
            },
        )

    def stop_for_step_limit(self) -> None:
        """Record a local runner's explicit safety cap as a normal stop event."""
        if not self.stopped:
            self._stop(StopReason.STEP_LIMIT, self._current_budget())

    def stop_for_runner_error(self) -> None:
        """Record a local runner abort without relying on a private environment API."""
        if not self.stopped:
            self._stop(StopReason.RUNNER_ERROR, self._current_budget())

    def record_evaluation(self, score: object, *, budget_before: float | None = None) -> None:
        """Let a local runner append the public evaluation result to the trace."""
        if not self._trace.enabled:
            return
        before = self._current_budget() if budget_before is None else budget_before
        after = self._trace_budget_after(before)
        self._emit(
            "evaluation.completed",
            before,
            after,
            {
                "score": score,
                "action_attempts": self.action_attempts,
                "action_successes": self.action_successes,
                "action_failures": self.action_failures,
                "remaining_budget": after,
                "stop_reason": self.stop_reason.value if self.stop_reason else None,
            },
        )

    def step(self) -> int:
        """Advance the state machine; diagnostics never control this flow."""
        # This consumes the last permitted outer call as a stop-only call.  It
        # leaves five calls of headroom beneath the published 120/250 limits.
        if self._step_number + 1 >= self.config.safety_step_limit(self.node_count):
            self._step_number += 1
            self._stop(StopReason.STEP_LIMIT, self._current_budget())
            return self._complete_step(1, self.state.value, self._current_budget())
        self._step_number += 1
        state_before = self.state.value
        budget_before = self._current_budget()
        self.last_action_attempted = False
        self.last_action_succeeded = None
        self.last_action_error = None
        self._last_trace_budget_after = None
        self._last_step_action = None
        self._last_step_action_result = "idle"
        self._last_step_selected_ids = []
        self._emit(
            "step.started",
            budget_before,
            budget_before,
            {"state_before": state_before, "action_attempts": self.action_attempts},
        )

        # State transitions have no environment action, so they may be consumed
        # in this dispatch slot until one public request is needed.
        for _ in range(8):
            if self.state is ControllerState.STOP:
                return self._complete_step(1, state_before, budget_before)

            budget = self._current_budget()
            if self.state is ControllerState.INIT:
                self._transition(ControllerState.SCAN_ALL, "initialized", budget)
                continue

            if self.state is ControllerState.SCAN_ALL:
                result = self._scan_next(budget)
                return self._complete_step(result, state_before, budget_before)

            if self.state is ControllerState.ANALYZE:
                self._refresh_candidates(budget, "analyze")
                if self._cmg_enabled:
                    self._transition(ControllerState.PLAN_CMG, "cmg_enabled", budget)
                elif self.candidates:
                    self._transition(ControllerState.PLAN_BATCH, "candidates_generated", budget)
                else:
                    self._stop(StopReason.NO_CANDIDATES, budget)
                continue

            if self.state is ControllerState.PLAN_BATCH:
                if self.analysis is None or not self.candidates:
                    self._stop(StopReason.NO_CANDIDATES, budget)
                    continue
                self._create_plan(budget)
                if self.queue:
                    self._transition(ControllerState.EXECUTE, "validated_queue_available", budget)
                else:
                    self._stop(StopReason.NO_VALID_ACTIONS, budget)
                continue

            if self.state is ControllerState.PLAN_CMG:
                result = self._plan_cmg(budget)
                if result is not None:
                    return self._complete_step(result, state_before, budget_before)
                continue

            if self.state is ControllerState.EXECUTE:
                result = self._execute_next(budget)
                return self._complete_step(result, state_before, budget_before)

            if self.state is ControllerState.REANALYZE:
                self._refresh_candidates(budget, "reanalyze")
                previous_queue = self.queue
                validation = self._valid_queue(previous_queue, budget)
                self.queue = list(validation.candidate_ids)
                self._emit_queue_revalidated("reanalysis", validation, budget)
                invalidated = len(previous_queue) - len(self.queue)
                if invalidated:
                    self.consecutive_invalid += invalidated
                if previous_queue and invalidated * 2 > len(previous_queue):
                    self.queue.clear()
                    self._emit(
                        "queue.revalidated",
                        budget,
                        budget,
                        {
                            "source": "reanalysis",
                            "enqueued_candidate_ids": [],
                            "discarded": [
                                {"candidate_id": candidate_id, "reason": "majority_invalidated"}
                                for candidate_id in validation.candidate_ids
                            ],
                        },
                    )
                if self.consecutive_invalid >= MAX_CONSECUTIVE_INVALID:
                    self.queue.clear()
                    self.consecutive_invalid = 0
                if self.queue:
                    self._transition(ControllerState.EXECUTE, "queue_revalidated", budget)
                elif self.candidates:
                    self._transition(ControllerState.PLAN_BATCH, "queue_empty_after_reanalysis", budget)
                else:
                    self._stop(StopReason.NO_VALID_ACTIONS, budget)
                continue

        self._stop(StopReason.STATE_GUARD, self._current_budget())
        return self._complete_step(1, state_before, budget_before)

    def _scan_next(self, budget: float) -> int:
        action = self.scout.next_action(self.blackboard)
        if action is None:
            self._transition(ControllerState.ANALYZE, "scan_exhausted", budget)
            self._emit("scan.completed", budget, budget, {"blackboard": self.blackboard.snapshot()})
            return 0
        if not is_legal_action(action, self.blackboard, budget):
            self._stop(StopReason.INSUFFICIENT_BUDGET, budget)
            return 1

        self._attempt_action(action, f"scan:{action.target_node_1}", budget)
        if self.scout.exhausted:
            completed_budget = (
                self._last_trace_budget_after
                if self._last_trace_budget_after is not None
                else budget
            )
            if self.config.stop_after_scan:
                self._stop(StopReason.NO_CANDIDATES, completed_budget)
            else:
                self._transition(ControllerState.ANALYZE, "scan_complete", completed_budget)
            self._emit(
                "scan.completed",
                budget,
                completed_budget,
                {"blackboard": self.blackboard.snapshot()},
            )
        return 0

    def _execute_next(self, budget: float) -> int:
        if self.cmg_candidate is not None:
            return self._execute_cmg(budget)
        if not self.queue:
            self._transition(ControllerState.REANALYZE, "queue_depleted", budget)
            return 0

        candidate_id = self.queue.pop(0)
        candidate = self.candidates.get(candidate_id)
        if candidate is None or candidate_id in self.failed_actions:
            self.consecutive_invalid += 1
            self._emit(
                "queue.revalidated",
                budget,
                budget,
                {
                    "source": "execute",
                    "enqueued_candidate_ids": list(self.queue),
                    "discarded": [{"candidate_id": candidate_id, "reason": "failed_or_unknown"}],
                },
            )
            self._transition(ControllerState.REANALYZE, "candidate_unavailable", budget)
            return 0
        if not is_legal_action(candidate.action, self.blackboard, budget):
            self.consecutive_invalid += 1
            self._emit(
                "queue.revalidated",
                budget,
                budget,
                {
                    "source": "execute",
                    "enqueued_candidate_ids": list(self.queue),
                    "discarded": [{"candidate_id": candidate_id, "reason": "illegal_action"}],
                },
            )
            self._transition(ControllerState.REANALYZE, "candidate_illegal", budget)
            return 0

        success = self._attempt_action(candidate.action, candidate_id, budget)
        if success:
            self.consecutive_invalid = 0
        else:
            self.failed_actions.add(candidate_id)
            self.consecutive_invalid += 1
        self._transition(
            ControllerState.REANALYZE,
            "action_succeeded" if success else "action_failed",
            self._last_trace_budget_after
            if self._last_trace_budget_after is not None
            else budget,
        )
        return 0

    @property
    def _cmg_enabled(self) -> bool:
        return (
            self.policy_mode is PolicyMode.V1_CMG
            and self.cmg_fallback_reason is None
            and self.calibration_profile.verified
        )

    def _fallback_to_v0(self, reason: str, budget: float) -> None:
        """Sticky, state-preserving escape hatch: never try CMG again this session."""
        if self.cmg_fallback_reason is None:
            self.cmg_fallback_reason = reason
            self._emit(
                "cmg.fallback",
                budget,
                budget,
                {"reason": reason, "profile_hash": self.calibration_profile.profile_hash or None},
            )
        self.cmg_candidate = None
        # Candidate generation may have happened before the failed CMG action.
        # Rebuild it so P0 exclusivity no longer hides lower-priority V0 work.
        self._transition(ControllerState.ANALYZE, "cmg_fallback", budget)

    def _plan_cmg(self, budget: float) -> int | None:
        """Plan exactly one action from a copied public state, without I/O."""
        try:
            candidate = choose_cmg_action(
                self.blackboard,
                self.response_ledger,
                self.calibration_profile,
                budget,
                cut_limit=self.config.cmg_cut_limit,
                iterations=self.config.cmg_iteration_limit,
                threshold=self.config.cmg_convergence_threshold,
                planning_seconds=self.config.cmg_planning_seconds,
            )
        except CMGPlanningError as exc:
            self._fallback_to_v0(str(exc), budget)
            return None
        if candidate is None:
            self._stop(StopReason.NO_POSITIVE_GAIN, budget)
            return None
        self.cmg_candidate = candidate
        self._last_step_selected_ids = [candidate.candidate_id]
        self._emit(
            "cmg.planned",
            budget,
            budget,
            self._cmg_trace_data(candidate),
        )
        self._transition(ControllerState.EXECUTE, "positive_cmg_action", budget)
        return None

    def _execute_cmg(self, budget: float) -> int:
        candidate = self.cmg_candidate
        if candidate is None or not is_legal_action(candidate.action, self.blackboard, budget):
            self._fallback_to_v0("illegal_hypothesis", budget)
            return 0
        before_w = None
        if candidate.action.kind == "comm":
            node = self.blackboard.nodes.get(candidate.action.target_node_1)
            before_w = node.w if node is not None else None
        success = self._attempt_action(candidate.action, candidate.candidate_id, budget)
        if success and candidate.action.kind == "comm" and before_w is not None:
            node = self.blackboard.nodes.get(candidate.action.target_node_1)
            if node is not None:
                try:
                    self.response_ledger.record_success(candidate.action.target_node_1, before_w, node.w)
                except CMGPlanningError as exc:
                    self._fallback_to_v0(str(exc), self._last_trace_budget_after or budget)
                    return 0
        if not success:
            self.failed_actions.add(candidate.candidate_id)
            self._fallback_to_v0("action_rejected", self._last_trace_budget_after or budget)
            return 0
        self.cmg_candidate = None
        next_budget = self._last_trace_budget_after if self._last_trace_budget_after is not None else budget
        self._transition(ControllerState.ANALYZE, "cmg_action_succeeded" if success else "cmg_action_failed", next_budget)
        return 0

    def _attempt_action(self, action: Action, candidate_id: str, budget: float) -> bool:
        self.last_action_attempted = True
        self.action_attempts += 1
        self._last_step_action = asdict(action)
        before_snapshot = self.blackboard.snapshot() if self._trace.enabled else None
        self._emit(
            "action.requested",
            budget,
            budget,
            {"candidate_id": candidate_id, "action": asdict(action)},
        )
        try:
            outcome = apply_action_outcome(self.env, self.blackboard, action, budget)
        except Exception as exc:
            self.last_action_succeeded = False
            self.last_action_error = type(exc).__name__
            self.action_failures += 1
            self._last_step_action_result = "exception"
            budget_after = self._trace_budget_after(budget)
            self._emit(
                "action.failed",
                budget,
                budget_after,
                {
                    "candidate_id": candidate_id,
                    "action": asdict(action),
                    "error": safe_error(exc),
                    "blackboard": self.blackboard.snapshot(),
                },
            )
            return False

        self.last_action_succeeded = outcome.succeeded
        budget_after = self._trace_budget_after(budget)
        if outcome.succeeded:
            self.action_successes += 1
            self._last_step_action_result = "success"
            self._emit(
                "action.completed",
                budget,
                budget_after,
                self._action_trace_data(candidate_id, outcome, before_snapshot),
            )
            return True

        self.action_failures += 1
        self._last_step_action_result = "failed"
        self._emit(
            "action.failed",
            budget,
            budget_after,
            self._action_trace_data(candidate_id, outcome, before_snapshot),
        )
        return False

    @staticmethod
    def _cmg_trace_data(candidate: ScoredCandidate) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "action": asdict(candidate.action),
            "score_before": candidate.score_before,
            "score_after": candidate.score_after,
            "gain": candidate.gain,
            "sigma": candidate.sigma,
            "lcb_roi": candidate.lcb_roi,
            "predicted_response_delta": candidate.response_delta,
        }

    def _action_trace_data(
        self,
        candidate_id: str,
        outcome: ActionOutcome,
        before_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "candidate_id": candidate_id,
            "action": asdict(outcome.action),
            "raw_response": outcome.raw_response,
            "success": outcome.succeeded,
            "rejected_reason": outcome.rejected_reason,
        }
        if before_snapshot is not None:
            data["blackboard_delta"] = self._blackboard_delta(
                before_snapshot, self.blackboard.snapshot()
            )
        return data

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        self.analysis = self.analyst.analyze(self.blackboard)
        candidates = self.analyst.generate_candidates(
            self.analysis,
            self.blackboard,
            budget,
            self.failed_actions,
            self.config,
        )
        self.candidates = {candidate.candidate_id: candidate for candidate in candidates}
        self._emit(
            "analysis.completed",
            budget,
            budget,
            self._analysis_trace_data(self.analysis, phase),
        )
        self._emit(
            "candidates.generated",
            budget,
            budget,
            {
                "phase": phase,
                "filtered_count": len(candidates),
                "candidates": [self._candidate_trace_data(candidate) for candidate in candidates],
            },
        )

    def _create_plan(self, budget: float) -> None:
        assert self.analysis is not None
        candidates = list(self.candidates.values())
        request_payload: Mapping[str, Any] | None = None
        if self.commander.can_request_llm:
            request_payload = self.commander.preview_payload(candidates, budget, self.analysis)
            self._emit(
                "llm.requested",
                budget,
                budget,
                {"payload": request_payload, "llm_call": self.commander.llm_calls + 1},
            )
        plan = self.commander.plan(
            candidates=candidates,
            budget=budget,
            analysis=self.analysis,
            request_payload=request_payload,
        )
        if plan.request_payload is not None and plan.error is None:
            self._emit(
                "llm.completed",
                budget,
                budget,
                {
                    "raw_output": plan.raw_response,
                    "parsed": {
                        "accepted": plan.source == "llm",
                        "candidate_ids": list(plan.parsed_candidate_ids),
                        "fallback_reason": plan.fallback_reason,
                    },
                    "llm_calls": self.commander.llm_calls,
                },
            )
        if plan.source != "llm" and (plan.request_payload is not None or plan.source == "quota_exhausted"):
            self._emit(
                "llm.failed",
                budget,
                budget,
                {
                    "source": plan.source,
                    "fallback_reason": plan.fallback_reason,
                    "error": plan.error,
                    "llm_calls": self.commander.llm_calls,
                },
            )
        validation = self._valid_queue(plan.candidate_ids, budget)
        self.queue = list(validation.candidate_ids)
        self._last_step_selected_ids = list(self.queue)
        self._emit(
            "plan.created",
            budget,
            budget,
            {
                "source": plan.source,
                "fallback_reason": plan.fallback_reason,
                "planned_candidate_ids": list(plan.candidate_ids),
                "selected_candidate_ids": list(self.queue),
                "llm_calls": self.commander.llm_calls,
            },
        )
        self._emit_queue_revalidated("plan", validation, budget)

    def _emit_queue_revalidated(
        self, source: str, validation: QueueValidation, budget: float
    ) -> None:
        self._emit(
            "queue.revalidated",
            budget,
            budget,
            {
                "source": source,
                "enqueued_candidate_ids": list(validation.candidate_ids),
                "discarded": list(validation.discarded),
            },
        )

    def _transition(self, state: ControllerState, reason: str, budget: float) -> None:
        if state is self.state:
            return
        previous = self.state
        self.state = state
        self._emit(
            "state.transition",
            budget,
            budget,
            {"old_state": previous.value, "new_state": state.value, "reason": reason},
        )

    def _stop(self, reason: StopReason, budget: float) -> None:
        if self.state is ControllerState.STOP:
            return
        self.stop_reason = reason
        self._transition(ControllerState.STOP, reason.value, budget)
        final_budget = self._trace_budget_after(budget)
        self._emit(
            "run.stopped",
            budget,
            final_budget,
            {
                "reason": reason.value,
                "blackboard": self.blackboard.snapshot(),
                "action_attempts": self.action_attempts,
                "action_successes": self.action_successes,
                "action_failures": self.action_failures,
                "remaining_budget": final_budget,
                "llm_calls": self.commander.llm_calls,
            },
        )

    def _complete_step(self, result: int, state_before: str, budget_before: float) -> int:
        budget_after = (
            self._last_trace_budget_after
            if self._last_trace_budget_after is not None
            else self._trace_budget_after(budget_before)
        )
        self._emit(
            "step.completed",
            budget_before,
            budget_after,
            {
                "state_before": state_before,
                "return_code": result,
                "action": self._last_step_action,
                "action_result": self._last_step_action_result,
                "action_attempts": self.action_attempts,
                "action_successes": self.action_successes,
                "action_failures": self.action_failures,
                "selected_candidate_ids": self._last_step_selected_ids,
            },
        )
        return result

    def _emit(
        self,
        event: str,
        budget_before: float | None,
        budget_after: float | None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        """Keep all controller records on the trace's best-effort boundary."""
        self._trace.emit(
            event,
            step=self._step_number,
            state=self.state.value,
            budget_before=budget_before,
            budget_after=budget_after,
            data=data,
        )

    def _current_budget(self) -> float:
        return float(self.env.get_remaining_budget())

    def _trace_budget_after(self, fallback: float) -> float:
        if not self._trace.enabled:
            return fallback
        try:
            budget = self._current_budget()
        except Exception:
            budget = fallback
        self._last_trace_budget_after = budget
        return budget

    @staticmethod
    def _candidate_trace_data(candidate: Candidate) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "action": asdict(candidate.action),
            "priority": candidate.priority,
            "score": candidate.score,
            "roi": candidate.roi,
            "reason": candidate.reason,
        }

    @staticmethod
    def _analysis_trace_data(analysis: GraphAnalysis, phase: str) -> dict[str, Any]:
        return {
            "phase": phase,
            "node_count": analysis.node_count,
            "edge_count": analysis.edge_count,
            "community_count": analysis.community_count,
            "node_metrics": {
                node_id: asdict(metrics) for node_id, metrics in sorted(analysis.node_metrics.items())
            },
            "edge_metrics": [
                {"edge": list(edge), **asdict(metrics)}
                for edge, metrics in sorted(analysis.edge_metrics.items())
            ],
        }

    @staticmethod
    def _blackboard_delta(
        before: Mapping[str, Any], after: Mapping[str, Any]
    ) -> dict[str, Any]:
        before_nodes = before.get("nodes", {})
        after_nodes = after.get("nodes", {})
        if not isinstance(before_nodes, Mapping) or not isinstance(after_nodes, Mapping):
            return {}
        before_edges = {tuple(edge) for edge in before.get("edges", [])}
        after_edges = {tuple(edge) for edge in after.get("edges", [])}
        before_dead = set(before.get("dead_nodes", []))
        after_dead = set(after.get("dead_nodes", []))
        common_nodes = set(before_nodes).intersection(after_nodes)
        return {
            "added_nodes": {
                node_id: after_nodes[node_id]
                for node_id in sorted(set(after_nodes).difference(before_nodes))
            },
            "removed_nodes": {
                node_id: before_nodes[node_id]
                for node_id in sorted(set(before_nodes).difference(after_nodes))
            },
            "updated_nodes": {
                node_id: {"before": before_nodes[node_id], "after": after_nodes[node_id]}
                for node_id in sorted(common_nodes)
                if before_nodes[node_id] != after_nodes[node_id]
            },
            "added_edges": [list(edge) for edge in sorted(after_edges.difference(before_edges))],
            "removed_edges": [list(edge) for edge in sorted(before_edges.difference(after_edges))],
            "added_dead_nodes": sorted(after_dead.difference(before_dead)),
            "removed_dead_nodes": sorted(before_dead.difference(after_dead)),
        }

    def _valid_queue(self, candidate_ids: Sequence[object], budget: float) -> QueueValidation:
        """Revalidate plan IDs against current facts, conflicts, and budget."""
        accepted: list[str] = []
        discarded: list[dict[str, str]] = []
        seen: set[str] = set()
        shielded_nodes: set[int] = set()
        cut_endpoints: set[int] = set()
        remaining = budget
        for raw_candidate_id in candidate_ids:
            if not isinstance(raw_candidate_id, str):
                discarded.append({"candidate_id": repr(raw_candidate_id), "reason": "invalid_id"})
                continue
            candidate_id = raw_candidate_id
            if len(accepted) >= MAX_BATCH_ACTIONS:
                discarded.append({"candidate_id": candidate_id, "reason": "batch_limit"})
                continue
            if candidate_id in seen:
                discarded.append({"candidate_id": candidate_id, "reason": "duplicate"})
                continue
            seen.add(candidate_id)
            candidate = self.candidates.get(candidate_id)
            if candidate is None:
                discarded.append({"candidate_id": candidate_id, "reason": "unknown_candidate"})
                continue
            if candidate_id in self.failed_actions:
                discarded.append({"candidate_id": candidate_id, "reason": "failed_action"})
                continue
            action = candidate.action
            cost = action_cost(action)
            if cost > remaining:
                discarded.append({"candidate_id": candidate_id, "reason": "insufficient_budget"})
                continue
            if not is_legal_action(action, self.blackboard, remaining):
                discarded.append({"candidate_id": candidate_id, "reason": "illegal_action"})
                continue
            if action.kind == "shield":
                if action.target_node_1 in cut_endpoints:
                    discarded.append({"candidate_id": candidate_id, "reason": "conflict"})
                    continue
                shielded_nodes.add(action.target_node_1)
            elif action.kind == "cut":
                assert action.target_node_2 is not None
                if action.target_node_1 in shielded_nodes or action.target_node_2 in shielded_nodes:
                    discarded.append({"candidate_id": candidate_id, "reason": "conflict"})
                    continue
                cut_endpoints.update((action.target_node_1, action.target_node_2))
            accepted.append(candidate_id)
            remaining -= cost
        return QueueValidation(tuple(accepted), tuple(discarded))


__all__ = [
    "BatchCommander",
    "BatchPlan",
    "ControllerState",
    "DeterministicScout",
    "GraphAnalyst",
    "MAX_LLM_CALLS",
    "QueueValidation",
    "RuntimeController",
    "StopReason",
    "infer_node_count",
]

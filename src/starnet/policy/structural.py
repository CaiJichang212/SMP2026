"""Fail-closed structural planning for B3 and B4.

The planner only operates on a copied :class:`PredictiveState`.  It never
calls the environment and never writes the Blackboard.  A plan is ordered as
``structure actions, then persuasion completion``; this makes it impossible
to count persuasion on a node that a later hypothetical shield removes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

import networkx as nx

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.cmg import PredictiveState, ResponseLedger, SettlementPredictor
from starnet.policy.config import PolicyMode


@dataclass(frozen=True)
class PlanCandidate:
    """A complete executable plan and its first public action."""

    candidate_id: str
    actions: tuple[Action, ...]
    first_action: Action | None
    cost: float
    steps: int
    predicted_final_score: float
    gain: float
    risk: float
    topology_summary: dict[str, Any]
    evidence_ids: tuple[str, ...] = ()
    structure_actions: tuple[Action, ...] = ()
    persuasion_actions: tuple[Action, ...] = ()

    @property
    def conservative_gain(self) -> float:
        return self.gain - self.risk

    @property
    def full_plan(self) -> tuple[Action, ...]:
        return self.actions

    @property
    def first_public_action(self) -> Action | None:
        return self.first_action

    @property
    def predicted_score(self) -> float:
        return self.predicted_final_score

    @property
    def valid(self) -> bool:
        return self.first_action is not None and self.cost >= 0 and self.steps == len(self.actions)


@dataclass(frozen=True)
class StructuralActionScore:
    action: Action
    score_before: float
    score_after: float
    gain: float
    risk: float
    category: str
    evidence_id: str


def _action_id(action: Action) -> str:
    if action.kind == "comm":
        return f"comm:{action.target_node_1}:{action.prompt_id}"
    if action.kind == "cut":
        return f"cut:{action.target_node_1}-{action.target_node_2}"
    return f"{action.kind}:{action.target_node_1}"


def _state_key(state: PredictiveState) -> tuple[object, ...]:
    return (
        tuple((node, state.nodes[node].w, state.nodes[node].persona, state.nodes[node].comm_left)
              for node in sorted(state.nodes)),
        tuple(sorted(state.edges)),
    )


class StructuralPlanner:
    """Deterministic B3 single-action and B4 depth-two beam planner."""

    def __init__(
        self,
        profile: CalibrationProfile,
        *,
        ledger: ResponseLedger | None = None,
        depth: int = 2,
        width: int = 4,
        candidate_limit: int = 12,
        predictor: SettlementPredictor | None = None,
        score_fn: Callable[[PredictiveState], float] | None = None,
    ) -> None:
        if depth <= 0 or width <= 0 or candidate_limit <= 0:
            raise ValueError("beam and candidate limits must be positive")
        self.profile = profile
        self.ledger = ledger or ResponseLedger()
        self.depth, self.width, self.candidate_limit = depth, width, candidate_limit
        self.predictor = predictor or SettlementPredictor(profile)
        self._score_fn = score_fn
        self._score_cache: dict[tuple[object, ...], float] = {}

    @property
    def _cache_safe(self) -> bool:
        """Only cache small-model scores; graph-state keys are expensive.

        The verified component score is O(V+E), while a cache key serialises
        every node and edge.  Retaining hundreds of such keys costs far more
        memory than recomputing the closed-form score on 50/100-node graphs.
        """
        return self._score_fn is not None or self.profile.model != "component_degree_plus_one"

    @property
    def eligible(self) -> bool:
        return self.profile.structure_eligible

    def _score(self, state: PredictiveState) -> float:
        if self._score_fn is not None:
            value = float(self._score_fn(state))
            if not math.isfinite(value):
                raise ValueError("nonfinite score")
            return value
        params = (self.profile.model, self.profile.rho, self.profile.gamma,
                  self.profile.a, self.profile.b, self.predictor.iterations,
                  self.predictor.threshold)
        key = params + _state_key(state)
        if not self._cache_safe:
            return float(self.predictor.score(state))
        if key not in self._score_cache:
            # Bound hypothetical-state retention for unverified/legacy models.
            # Eviction changes neither a score nor candidate ordering.
            if len(self._score_cache) >= 256:
                self._score_cache.clear()
            self._score_cache[key] = float(self.predictor.score(state))
        return self._score_cache[key]

    def influence_coefficients(self, state: PredictiveState, delta: float = 1.0) -> dict[int, float]:
        """Recompute score sensitivities for this exact topology."""
        if delta <= 0 or not math.isfinite(delta):
            raise ValueError("delta must be positive and finite")
        base = self._score(state)
        result: dict[int, float] = {}
        for node_id in sorted(state.nodes):
            changed = PredictiveState(
                nodes={node: type(value)(value.w, value.persona, value.comm_left)
                       for node, value in state.nodes.items()},
                edges=set(state.edges), dead_nodes=set(state.dead_nodes),
            )
            changed.nodes[node_id].w += delta
            result[node_id] = (self._score(changed) - base) / delta
        return result

    def _structure_scores(self, state: PredictiveState, budget: float) -> list[StructuralActionScore]:
        board = state.to_blackboard()
        before = self._score(state)
        scores: list[StructuralActionScore] = []
        # Full scans by action class are intentional: candidate coverage must
        # not be replaced by a negative-node/bridge heuristic.
        actions = [Action("shield", node_id) for node_id in sorted(state.nodes)]
        actions += [Action("cut", left, target_node_2=right) for left, right in sorted(state.edges)]
        residuals = self.profile.structure_action_residual_std or self.profile.settlement_residual_std
        for action in actions:
            if not is_legal_action(action, board, budget):
                continue
            after_state = state.apply(action)
            after = self._score(after_state)
            residual = float(residuals.get(action.kind, math.inf))
            if not math.isfinite(residual):
                continue
            category = "shield" if action.kind == "shield" else "cut"
            scores.append(StructuralActionScore(
                action, before, after, after - before, max(0.0, residual), category,
                f"structure:{_action_id(action)}",
            ))
        return scores

    def structure_candidates(self, board: Blackboard, budget: float) -> tuple[StructuralActionScore, ...]:
        """Cheap full scan + class-balanced finite scoring layer."""
        if not self.eligible:
            return ()
        raw = self._structure_scores(PredictiveState.from_blackboard(board), budget)
        selected: list[StructuralActionScore] = []
        for category in ("shield", "cut"):
            category_items = sorted(
                (item for item in raw if item.category == category),
                key=lambda item: (-item.gain, item.action.kind, _action_id(item.action)),
            )
            selected.extend(category_items[:4])
        selected_ids = {_action_id(item.action) for item in selected}
        remainder = sorted(
            (item for item in raw if _action_id(item.action) not in selected_ids),
            key=lambda item: (-item.gain, item.action.kind, _action_id(item.action)),
        )
        selected.extend(remainder[:max(0, self.candidate_limit - len(selected))])
        return tuple(selected[: self.candidate_limit])

    # Names kept deliberately small for experiment drivers and notebooks.
    score_actions = structure_candidates

    def _response_delta(self, state: PredictiveState, action: Action) -> float | None:
        node = state.nodes.get(action.target_node_1)
        if node is None or action.prompt_id is None:
            return None
        turn = 4 - int(node.comm_left or 0)
        if turn not in (1, 2, 3):
            return None
        response = self.ledger.predicted_delta(
            action.target_node_1, node.persona, action.prompt_id, self.profile, turn=turn
        )
        return None if response is None else max(0.0, float(response[0]))

    def _complete_persuasion(
        self, state: PredictiveState, budget: float, remaining_steps: int,
    ) -> tuple[PredictiveState, tuple[Action, ...], float]:
        """Fill residual resources greedily after all structure actions."""
        actions: list[Action] = []
        current = state
        left_budget, left_steps = budget, remaining_steps
        linear_influence: dict[int, float] | None = None
        if self.profile.model == "component_degree_plus_one":
            # For a fixed topology the verified component score is linear in
            # every w_i.  Compute its exact coefficient once; repeated
            # persuasion hypotheses then need no graph copy or connectivity
            # recomputation.  Structure actions still create fresh topologies
            # and therefore recompute this map per terminal candidate.
            linear_influence = self.influence_coefficients(current)
        while left_budget >= 2.0 and left_steps > 0:
            board = current.to_blackboard()
            if linear_influence is not None:
                options_linear: list[tuple[float, str, Action, float]] = []
                for node_id in sorted(current.nodes):
                    action = Action("comm", node_id, prompt_id=1)
                    if not is_legal_action(action, board, left_budget):
                        continue
                    delta = self._response_delta(current, action)
                    if delta is None:
                        continue
                    gain = linear_influence.get(node_id, 0.0) * delta
                    if math.isfinite(gain) and gain > 0:
                        options_linear.append((gain, _action_id(action), action, delta))
                if not options_linear:
                    break
                _, _, action, delta = max(options_linear, key=lambda item: (item[0], "".join(reversed(item[1]))))
                current = current.apply(action, delta)
            else:
                options: list[tuple[float, str, Action, PredictiveState]] = []
                current_score = self._score(current)
                for node_id in sorted(current.nodes):
                    action = Action("comm", node_id, prompt_id=1)
                    if not is_legal_action(action, board, left_budget):
                        continue
                    delta = self._response_delta(current, action)
                    if delta is None:
                        continue
                    after_state = current.apply(action, delta)
                    gain = self._score(after_state) - current_score
                    if math.isfinite(gain) and gain > 0:
                        options.append((gain, _action_id(action), action, after_state))
                if not options:
                    break
                _, _, action, current = max(options, key=lambda item: (item[0], "".join(reversed(item[1]))))
            actions.append(action)
            left_budget -= action_cost(action)
            left_steps -= 1
        return current, tuple(actions), budget - left_budget

    def _make_plan(
        self, initial: PredictiveState, structure: tuple[Action, ...],
        budget: float, remaining_steps: int, baseline_score: float,
    ) -> PlanCandidate | None:
        state = initial
        left_budget, left_steps = budget, remaining_steps
        for action in structure:
            board = state.to_blackboard()
            if left_steps <= 0 or not is_legal_action(action, board, left_budget):
                return None
            state = state.apply(action)
            left_budget -= action_cost(action)
            left_steps -= 1
        structure_state = state
        state, persuasion, _persuasion_cost = self._complete_persuasion(state, left_budget, left_steps)
        actions = structure + persuasion
        if not actions:
            return PlanCandidate("complete", (), None, 0.0, 0, baseline_score, 0.0, 0.0,
                                 self._topology_summary(initial), (), (), ())
        cost = sum(action_cost(action) for action in actions)
        residuals = self.profile.structure_action_residual_std or self.profile.settlement_residual_std
        risk_sq = sum(float(residuals.get(action.kind, 0.0)) ** 2 for action in structure)
        # Response priors are expressed in opinion units while the plan gain
        # is terminal-score units.  Reproduce each hypothetical communication
        # from its pre-action state and transform ± one standard deviation
        # through the same settlement predictor before combining uncertainty.
        risk_state = structure_state
        comm_residual = float(residuals.get("comm", self.profile.residual_for("comm")))
        for action in persuasion:
            node = risk_state.nodes.get(action.target_node_1)
            if node is None or action.prompt_id is None or node.comm_left is None:
                return None
            turn = 4 - node.comm_left
            response = self.ledger.predicted_delta(
                action.target_node_1, node.persona, action.prompt_id, self.profile, turn=turn
            )
            if response is None:
                return None
            delta, response_std = max(0.0, float(response[0])), max(0.0, float(response[1]))
            mean_state = risk_state.apply(action, delta)
            mean_score = self._score(mean_state)
            if response_std > 0.0:
                high_score = self._score(risk_state.apply(action, delta + response_std))
                low_score = self._score(risk_state.apply(action, delta - response_std))
                response_score_std = max(abs(high_score - mean_score), abs(mean_score - low_score))
            else:
                response_score_std = 0.0
            if not math.isfinite(comm_residual) or not math.isfinite(response_score_std):
                return None
            risk_sq += math.hypot(comm_residual, response_score_std) ** 2
            risk_state = mean_state
        final_score = self._score(state)
        gain = final_score - baseline_score
        identifier = "plan:" + "|".join(_action_id(action) for action in actions)
        return PlanCandidate(
            identifier, actions, actions[0], cost, len(actions), final_score, gain,
            math.sqrt(max(0.0, risk_sq)), self._topology_summary(state),
            tuple(f"plan:{_action_id(action)}" for action in actions),
            structure, persuasion,
        )

    @staticmethod
    def _topology_summary(state: PredictiveState) -> dict[str, Any]:
        graph = nx.Graph()
        graph.add_nodes_from(state.nodes)
        graph.add_edges_from(state.edges)
        return {
            "nodes": len(state.nodes),
            "edges": len(state.edges),
            "components": 0 if not state.nodes else nx.number_connected_components(graph),
            "shielded": sorted(state.dead_nodes),
        }

    def plan_candidates(
        self, board: Blackboard, budget: float, remaining_steps: int,
        mode: PolicyMode = PolicyMode.B4_BEAM_STRUCTURE,
    ) -> tuple[PlanCandidate, ...]:
        if not self.eligible:
            return ()
        initial = PredictiveState.from_blackboard(board)
        baseline_score = self._score(initial)
        baseline = self._make_plan(initial, (), budget, remaining_steps, baseline_score)
        if baseline is None:
            return ()
        if mode is PolicyMode.B3_SINGLE_STRUCTURE:
            # Score every legal structure action for coverage, but retain only
            # the same bounded set that can later become runnable candidates.
            # Keeping every full persuasion completion is the dominant memory
            # cost on 100-node dense graphs.
            plans: list[PlanCandidate] = [baseline]
            for item in self.structure_candidates(board, budget):
                plan = self._make_plan(initial, (item.action,), budget, remaining_steps, baseline_score)
                if plan is not None and plan.conservative_gain > 0:
                    plans.append(plan)
                    plans = sorted(plans, key=lambda item: (-item.conservative_gain, item.candidate_id))[: self.candidate_limit + 1]
            return tuple(sorted(plans, key=lambda item: (-item.conservative_gain, item.candidate_id)))

        # Beam state keeps structural actions only.  Every terminal state is
        # independently completed with persuasion and can stop immediately.
        pool = list(self.structure_candidates(board, budget))
        beam: list[tuple[PredictiveState, tuple[Action, ...]]] = [(initial, ())]
        terminals: list[PlanCandidate] = [baseline]
        for _depth in range(min(self.depth, remaining_steps)):
            expanded: list[tuple[float, str, PredictiveState, tuple[Action, ...]]] = []
            for state, sequence in beam:
                available = sorted(
                    self._structure_scores(state, budget - sum(action_cost(a) for a in sequence)),
                    key=lambda item: (-item.gain, _action_id(item.action)),
                )
                # The root keeps the bounded candidate pool (which is class
                # balanced); later beam layers need only the top width local
                # expansions.  Evaluating a complete persuasion tail for all
                # hundreds of edges is not a beam search and dominates both
                # runtime and allocator churn on 100-node graphs.
                limit = self.candidate_limit if not sequence else self.width
                available = available[:limit]
                for item in available:
                    if item.action in sequence:
                        continue
                    next_sequence = sequence + (item.action,)
                    plan = self._make_plan(initial, next_sequence, budget, remaining_steps, baseline_score)
                    if plan is not None:
                        terminals.append(plan)
                        expanded.append((plan.conservative_gain, plan.candidate_id,
                                         state.apply(item.action), next_sequence))
            # Only the top beam can be expanded and only the top runnable
            # plans can reach the controller; discard the rest immediately.
            terminals = sorted(
                terminals, key=lambda item: (-item.conservative_gain, item.candidate_id)
            )[: self.candidate_limit + 1]
            unique: dict[tuple[object, ...], tuple[float, str, PredictiveState, tuple[Action, ...]]] = {}
            for item in sorted(expanded, key=lambda value: (-value[0], value[1])):
                unique.setdefault(_state_key(item[2]), item)
            beam = [(item[2], item[3]) for item in list(unique.values())[: self.width]]
            if not beam:
                break
        accepted = [item for item in terminals if item.conservative_gain > 0 or not item.structure_actions]
        # Deduplicate plans and make the stable ordering explicit.
        dedup = {item.candidate_id: item for item in accepted}
        return tuple(sorted(dedup.values(), key=lambda item: (-item.conservative_gain, item.candidate_id))[: self.candidate_limit + 1])

    def plan(
        self, board: Blackboard, budget: float, remaining_steps: int,
        mode: PolicyMode = PolicyMode.B4_BEAM_STRUCTURE,
    ) -> PlanCandidate | None:
        """Return the best complete plan, or ``None`` when the gate is closed."""
        plans = self.plan_candidates(board, budget, remaining_steps, mode)
        return plans[0] if plans else None


__all__ = ["PlanCandidate", "StructuralActionScore", "StructuralPlanner"]

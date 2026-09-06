"""B5 adaptive exploration primitives.

The scenario layer is deliberately small and explicit.  A scenario is a
possible completion of unknown facts, never a replacement for Blackboard
facts.  If validation is unavailable, callers must use the deterministic
full-scan scout.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
import random

import networkx as nx

from starnet.model.blackboard import Blackboard, NodeState
from starnet.policy.actions import Action
from starnet.policy.cmg import PredictiveState


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    state: PredictiveState
    observations: Mapping[int, Mapping[str, object]]
    weight: float = 1.0


@dataclass(frozen=True)
class ScenarioProfile:
    """Independently validated hidden-state hypotheses for B5."""

    scenarios: tuple[Scenario, ...] = ()
    gate_passed: bool = False
    independent_validation_passed: bool = False

    @property
    def verified(self) -> bool:
        return (
            self.gate_passed and self.independent_validation_passed
            and bool(self.scenarios)
            and all(math.isfinite(float(item.weight)) and item.weight >= 0 for item in self.scenarios)
            and sum(item.weight for item in self.scenarios) > 0
        )

    @classmethod
    def from_states(cls, states: Sequence[PredictiveState]) -> "ScenarioProfile":
        scenarios = tuple(
            Scenario(str(index), state, {}, 1.0) for index, state in enumerate(states)
        )
        return cls(scenarios, True, True)

    def normalized(self) -> tuple[tuple[Scenario, float], ...]:
        total = sum(max(0.0, float(item.weight)) for item in self.scenarios)
        if not self.verified or total <= 0:
            return ()
        return tuple((item, float(item.weight) / total) for item in self.scenarios)

    def is_consistent(self, board: Blackboard) -> bool:
        """Reject scenarios contradicting any observed node, edge, or non-edge."""
        if not self.verified:
            return False
        for scenario, _weight in self.normalized():
            # A public unavailable/shielded result is a fact, not a latent
            # variable.  A scenario retaining that node (or an incident edge)
            # cannot be used for a later VOI calculation.
            if (
                board.dead_nodes.intersection(scenario.state.nodes)
                or not board.dead_nodes.issubset(scenario.state.dead_nodes)
                or any(board.dead_nodes.intersection(edge) for edge in scenario.state.edges)
                or board.dead_nodes.intersection(scenario.observations)
            ):
                return False
            for node_id, observed in board.nodes.items():
                possible = scenario.state.nodes.get(node_id)
                if possible is None:
                    return False
                if (
                    not math.isclose(possible.w, observed.w, abs_tol=1e-9)
                    or possible.persona != observed.persona
                    or possible.comm_left != observed.comm_left
                ):
                    return False
            if not board.edges.issubset(scenario.state.edges):
                return False
            if any(edge in scenario.state.edges for edge in board.confirmed_non_edges):
                return False
            # A recorded scan response is part of the scenario's hidden state;
            # accepting a payload that contradicts it would fabricate VOI.
            for node_id, payload in scenario.observations.items():
                possible = scenario.state.nodes.get(node_id)
                if possible is None or not _observation_matches_state(node_id, payload, scenario.state):
                    return False
        return True


@dataclass(frozen=True)
class ScanValue:
    node_id: int
    voi: float
    evidence_ids: tuple[str, ...]


def _apply_observation(state: PredictiveState, node_id: int, payload: Mapping[str, object]) -> PredictiveState | None:
    raw_w = payload.get("w")
    persona = payload.get("persona")
    raw_comm = payload.get("comm_left")
    neighbors = payload.get("neighbors")
    if not isinstance(raw_w, (int, float)) or isinstance(raw_w, bool) or not math.isfinite(float(raw_w)):
        return None
    if not isinstance(persona, str) or not isinstance(neighbors, list):
        return None
    if raw_comm is not None and (not isinstance(raw_comm, int) or isinstance(raw_comm, bool)):
        return None
    nodes = {key: NodeState(value.w, value.persona, value.comm_left) for key, value in state.nodes.items()}
    nodes[node_id] = NodeState(float(raw_w), persona, raw_comm)
    edges = {edge for edge in state.edges if node_id not in edge}
    for neighbor in neighbors:
        if isinstance(neighbor, int) and not isinstance(neighbor, bool) and neighbor != node_id:
            edges.add((min(node_id, neighbor), max(node_id, neighbor)))
    return PredictiveState(nodes, edges, set(state.dead_nodes))


def _scenario_observation(scenario: Scenario, node_id: int) -> Mapping[str, object] | None:
    """Return the fixed scan result implied by one complete scenario."""
    recorded = scenario.observations.get(node_id)
    if recorded is not None:
        return recorded
    node = scenario.state.nodes.get(node_id)
    if node is None or node_id in scenario.state.dead_nodes:
        return None
    return {
        "w": node.w,
        "persona": node.persona,
        "comm_left": node.comm_left,
        "neighbors": sorted(
            right if left == node_id else left
            for left, right in scenario.state.edges
            if node_id in (left, right)
        ),
    }


def _observation_matches_state(
    node_id: int, payload: Mapping[str, object], state: PredictiveState
) -> bool:
    """Check that a recorded scenario observation does not contradict state."""
    expected = _scenario_observation(Scenario("", state, {}, 1.0), node_id)
    if expected is None:
        return False
    return (
        payload.get("w") == expected["w"]
        and payload.get("persona") == expected["persona"]
        and payload.get("comm_left", expected["comm_left"]) == expected["comm_left"]
        and isinstance(payload.get("neighbors"), list)
        and sorted(payload["neighbors"]) == expected["neighbors"]
    )


def evaluate_scan_voi(
    board: Blackboard,
    node_id: int,
    profile: ScenarioProfile,
    value_fn: Callable[[PredictiveState], float],
    *,
    branch_value_fn: Callable[[PredictiveState], float] | None = None,
    scan_cost: float = 0.5,
) -> ScanValue:
    """Evaluate a fixed prior and its observation branches without resampling.

    ``value_fn`` evaluates the current public state.  ``branch_value_fn`` (or
    ``value_fn`` when omitted) evaluates that same state after one fixed scan
    result; callers normally give it the reduced budget/step envelope.  Thus
    the branch can rerun a bounded legal planner without peeking at the
    scenario's full hidden state.  Set ``scan_cost`` to zero only when the
    branch function already receives reduced resources.
    """
    if not profile.is_consistent(board) or not board.can_scan(node_id):
        return ScanValue(node_id, -math.inf, ())
    before_state = PredictiveState.from_blackboard(board)
    before = float(value_fn(before_state))
    if not math.isfinite(before):
        return ScanValue(node_id, -math.inf, ())
    weighted_after = 0.0
    evidence: list[str] = []
    for scenario, weight in profile.normalized()[:8]:
        observation = _scenario_observation(scenario, node_id)
        after_state = _apply_observation(before_state, node_id, observation) if observation else None
        if after_state is None:
            # A scenario without an observation does not create artificial VOI.
            after = before
        else:
            after = float((branch_value_fn or value_fn)(after_state))
            evidence.append(f"scenario:{scenario.scenario_id}:scan:{node_id}")
        if not math.isfinite(before) or not math.isfinite(after):
            return ScanValue(node_id, -math.inf, tuple(evidence))
        weighted_after += weight * after
    # The value function is evaluated on the same scenario before and after;
    # charge the information action exactly once here.
    return ScanValue(node_id, weighted_after - before - scan_cost, tuple(evidence))


class AdaptiveScout:
    """Frontier/blind mixed scout with deterministic pseudo-random starts."""

    def __init__(self, node_count: int, *, initial_count: int, seed: int = 20260905) -> None:
        if node_count <= 0 or initial_count <= 0:
            raise ValueError("node_count and initial_count must be positive")
        self.node_count = node_count
        self.initial_count = min(node_count, initial_count)
        self._rng = random.Random(seed)
        self._initial = iter(sorted(self._rng.sample(range(1, node_count + 1), self.initial_count)))
        self.scan_count = 0

    @property
    def exhausted(self) -> bool:
        return self.scan_count >= self.node_count

    def _rank(self, board: Blackboard) -> list[int]:
        unknown = [node for node in range(1, self.node_count + 1) if board.can_scan(node)]
        frontier = board.frontier_ids
        graph = nx.Graph()
        graph.add_edges_from(board.edges)
        seen_components: dict[int, int] = {}
        for component_id, component in enumerate(nx.connected_components(graph)):
            for node in component:
                seen_components[node] = component_id
        coverage: dict[int, int] = {}
        for node in board.nodes:
            component = seen_components.get(node, node)
            coverage[component] = coverage.get(component, 0) + 1
        def key(node: int) -> tuple[int, int, int, int]:
            adjacent_seen = sum(node in edge for edge in board.edges)
            region = seen_components.get(node, node)
            return (0 if node in frontier else 1, -adjacent_seen, coverage.get(region, 0), node)
        return sorted(unknown, key=key)

    def candidate_ids(self, board: Blackboard) -> tuple[int, ...]:
        """Expose the bounded frontier/blind pool without consuming a scan."""
        return tuple(self._rank(board))

    def next_action(self, board: Blackboard, *, voi: Mapping[int, float] | None = None) -> Action | None:
        while True:
            try:
                node_id = next(self._initial)
            except StopIteration:
                break
            if board.can_scan(node_id):
                self.scan_count += 1
                return Action("scan", node_id)
        choices = self._rank(board)
        if voi:
            choices = sorted(choices, key=lambda node: (-float(voi.get(node, -math.inf)), node))
        if not choices:
            return None
        self.scan_count += 1
        return Action("scan", choices[0])


__all__ = ["AdaptiveScout", "ScanValue", "Scenario", "ScenarioProfile", "evaluate_scan_voi"]

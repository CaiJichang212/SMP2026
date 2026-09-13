"""P2 structural planner regression cases and conservation checks."""

from __future__ import annotations

from dataclasses import asdict
import unittest
from unittest.mock import patch

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.cmg import PredictiveState
from starnet.policy.config import PolicyMode
from starnet.policy.structural import (
    ExperimentalPublicGreedyPlanner,
    StructuralPlanner,
    public_structure_risk_allowed,
)


def active_profile() -> CalibrationProfile:
    draft = CalibrationProfile(
        gate_passed=True,
        structure_gate_passed=True,
        model="degree",
        settlement_residual_std={"comm": 0.0, "cut": 0.0, "shield": 0.0},
        structure_action_residual_std={"comm": 0.0, "cut": 0.0, "shield": 0.0},
        response_mean={"和平|1|1": 2.0, "和平|1|2": 1.0, "和平|1|3": 0.5},
        response_std={"和平|1|1": 0.0, "和平|1|2": 0.0, "和平|1|3": 0.0},
        target_influence={str(node): 1.0 for node in range(1, 8)},
        manifest_hash="manifest",
        data_hash="data",
    )
    return CalibrationProfile(**{**asdict(draft), "profile_hash": draft.computed_hash()})


def board(nodes: dict[int, tuple[float, str, int]], edges: list[tuple[int, int]]) -> Blackboard:
    result = Blackboard()
    neighbors = {node: [] for node in nodes}
    for left, right in edges:
        neighbors[left].append(right)
        neighbors[right].append(left)
    for node, (weight, persona, comm_left) in nodes.items():
        result.record_scan(node, {"w": weight, "persona": persona, "comm_left": comm_left,
                                  "neighbors": neighbors[node]})
    return result


def degree_weighted(state: PredictiveState) -> float:
    return sum(sum(node in edge for edge in state.edges) * state.nodes[node].w for node in state.nodes)


class StructuralPlannerTests(unittest.TestCase):
    def test_closed_public_gate_skips_structural_counterfactuals(self) -> None:
        graph = board({node: (20.0, "和平", 3) for node in range(1, 4)},
                      [(1, 2), (2, 3), (1, 3)])
        planner = ExperimentalPublicGreedyPlanner(lambda *_: 15.0, min_observed_responses=0)
        with patch.object(planner.predictor, "score", wraps=planner.predictor.score) as score:
            candidates = planner.candidates(graph, 20.0)
        # Communications already have their exact linear gain; only the
        # original topology requires scoring when structure is disabled.
        self.assertEqual(score.call_count, 1)
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(candidate.action.kind == "comm" for candidate in candidates))

    def test_experimental_public_greedy_selects_positive_terminal_gain(self) -> None:
        graph = board(
            {1: (-40.0, "暴力", 3), 2: (10.0, "和平", 3), 3: (10.0, "和平", 3)},
            [(1, 2), (1, 3)],
        )
        planner = ExperimentalPublicGreedyPlanner(
            lambda _node_id, _node, _turn: 15.0,
            min_observed_responses=0,
            structure_roi_margin=1.0,
        )
        candidates = planner.candidates(graph, 20.0)

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].action.kind, "shield")
        self.assertEqual(candidates[0].action.target_node_1, 1)
        self.assertTrue(all(candidate.score > 0.0 for candidate in candidates))

    def test_public_structure_gate_closes_positive_peace_majority(self) -> None:
        graph = board(
            {1: (-8.0, "暴力", 3), **{
                node: (20.0 - node, "和平", 3) for node in range(2, 10)
            }},
            [(node, node + 1) for node in range(1, 9)],
        )
        self.assertFalse(public_structure_risk_allowed(graph, Action("shield", 1), 10.0))
        planner = ExperimentalPublicGreedyPlanner(
            lambda _node_id, _node, _turn: 15.0,
            min_observed_responses=0,
            structure_roi_margin=1.0,
        )
        candidates = planner.candidates(graph, 20.0)
        self.assertFalse(any(item.action.kind in {"cut", "shield"} for item in candidates))

    def test_public_structure_gate_allows_negative_violent_center(self) -> None:
        graph = board(
            {1: (-40.0, "暴力", 3), 2: (10.0, "和平", 3), 3: (10.0, "和平", 3)},
            [(1, 2), (1, 3)],
        )
        self.assertTrue(public_structure_risk_allowed(graph, Action("shield", 1), 1.0))
        planner = ExperimentalPublicGreedyPlanner(
            lambda _node_id, _node, _turn: 15.0,
            min_observed_responses=0,
            structure_roi_margin=1.0,
        )
        candidates = planner.candidates(graph, 20.0)
        self.assertEqual(candidates[0].action, Action("shield", 1))

    def test_public_structure_gate_allows_negative_neutral_node_outside_positive_gate(self) -> None:
        graph = board(
            {1: (-12.0, "中立", 3), 2: (8.0, "和平", 3), 3: (7.0, "和平", 3)},
            [(1, 2), (1, 3)],
        )
        self.assertTrue(public_structure_risk_allowed(graph, Action("shield", 1), 1.0))

    def test_negative_center_can_damage_positive_neighbors(self) -> None:
        graph = board({1: (-1.0, "暴力", 0), **{node: (10.0, "和平", 0) for node in range(2, 6)}},
                      [(1, 2), (1, 3), (1, 4), (1, 5)])
        planner = StructuralPlanner(active_profile(), score_fn=degree_weighted)
        center = next(item for item in planner.structure_candidates(graph, 10.0)
                      if item.action.kind == "shield" and item.action.target_node_1 == 1)
        self.assertLess(center.gain, 0.0)

    def test_cutting_favorable_bridge_is_not_assumed_to_help(self) -> None:
        graph = board({1: (8.0, "和平", 0), 2: (9.0, "和平", 0)}, [(1, 2)])
        planner = StructuralPlanner(active_profile(), score_fn=degree_weighted)
        edge = next(item for item in planner.structure_candidates(graph, 10.0) if item.action.kind == "cut")
        self.assertLess(edge.gain, 0.0)

    def test_influence_is_recomputed_after_topology_change(self) -> None:
        graph = board({1: (1.0, "和平", 0), 2: (1.0, "和平", 0), 3: (1.0, "和平", 0)},
                      [(1, 2), (2, 3)])
        planner = StructuralPlanner(active_profile(), score_fn=degree_weighted)
        before = planner.influence_coefficients(PredictiveState.from_blackboard(graph))
        changed = PredictiveState.from_blackboard(graph).apply(Action("cut", 1, 2))
        after = planner.influence_coefficients(changed)
        self.assertNotEqual(before, after)

    def test_component_score_does_not_retain_full_graph_state_cache(self) -> None:
        profile = active_profile()
        payload = asdict(profile)
        payload["model"] = "component_degree_plus_one"
        payload["profile_hash"] = ""
        component = CalibrationProfile(**payload)
        component = CalibrationProfile(**{**asdict(component), "profile_hash": component.computed_hash()})
        graph = board({node: (float(node), "和平", 3) for node in range(1, 8)}, [(node, node + 1) for node in range(1, 7)])
        planner = StructuralPlanner(component)
        planner.structure_candidates(graph, 20.0)
        self.assertEqual(planner._score_cache, {})

    def test_b4_can_keep_a_complete_negative_first_combo(self) -> None:
        graph = board({1: (0.0, "中立", 0), 2: (0.0, "中立", 0), 3: (0.0, "中立", 0)},
                      [(1, 2), (2, 3)])
        def paired_cuts(state: PredictiveState) -> float:
            return 1.0 if not state.edges and not state.dead_nodes else 0.0
        planner = StructuralPlanner(active_profile(), depth=2, width=4, score_fn=paired_cuts)
        plans = planner.plan_candidates(graph, 6.0, 2, PolicyMode.B4_BEAM_STRUCTURE)
        self.assertTrue(any(len(plan.structure_actions) == 2 and plan.gain > 0 for plan in plans))
        single = planner.plan_candidates(graph, 6.0, 2, PolicyMode.B3_SINGLE_STRUCTURE)
        self.assertFalse(any(plan.structure_actions and plan.gain > 0 for plan in single))

    def test_opt_in_pair_cut_experiment_keeps_jointly_useful_cuts_pruned_by_beam(self) -> None:
        # The two useful edges lie beyond B4's class-balanced root cut set.
        # Neither singleton changes the score.  This models a negative cluster
        # that is only separated once both boundary links are removed.
        edges = [(node, node + 1) for node in range(1, 15)]
        graph = board({node: (0.0, "中立", 0) for node in range(1, 16)}, edges)
        target = {(13, 14), (14, 15)}

        def only_joint_pair(state: PredictiveState) -> float:
            return 10.0 if target.isdisjoint(state.edges) and not state.dead_nodes else 0.0

        ordinary = StructuralPlanner(
            active_profile(), depth=2, width=1, candidate_limit=12, score_fn=only_joint_pair,
        ).plan_candidates(graph, 6.0, 2, PolicyMode.B4_BEAM_STRUCTURE)
        self.assertFalse(any(plan.gain > 0.0 for plan in ordinary))

        experimental = StructuralPlanner(
            active_profile(), depth=2, width=1, candidate_limit=12,
            enable_pair_cut_experiment=True, pair_cut_edge_limit=16, pair_cut_plan_limit=6,
            score_fn=only_joint_pair,
        ).plan_candidates(graph, 6.0, 2, PolicyMode.B4_BEAM_STRUCTURE)
        pair = next(plan for plan in experimental if plan.gain > 0.0)
        self.assertEqual(set(pair.structure_actions), {
            Action("cut", 13, 14), Action("cut", 14, 15),
        })
        self.assertEqual(pair.cost, 6.0)
        self.assertTrue(all(action.kind == "cut" for action in pair.actions))

    def test_pair_cut_experiment_limits_are_bounded(self) -> None:
        with self.assertRaises(ValueError):
            StructuralPlanner(active_profile(), enable_pair_cut_experiment=True, pair_cut_edge_limit=17)

    def test_persuasion_is_only_scheduled_after_structure_and_never_on_shielded_node(self) -> None:
        graph = board({1: (-2.0, "暴力", 0), 2: (3.0, "和平", 3), 3: (3.0, "和平", 3)},
                      [(1, 2), (2, 3)])
        planner = StructuralPlanner(active_profile(), score_fn=degree_weighted)
        plans = planner.plan_candidates(graph, 10.0, 4, PolicyMode.B4_BEAM_STRUCTURE)
        for plan in plans:
            shielded = {action.target_node_1 for action in plan.structure_actions if action.kind == "shield"}
            self.assertFalse(any(action.target_node_1 in shielded for action in plan.persuasion_actions))

    def test_response_uncertainty_is_transformed_at_the_actual_turn_and_score_scale(self) -> None:
        draft = active_profile()
        payload = asdict(draft)
        payload["response_mean"] = {"和平|1|2": 1.0}
        payload["response_std"] = {"和平|1|2": 3.0}
        payload["profile_hash"] = ""
        calibrated = CalibrationProfile(**payload)
        calibrated = CalibrationProfile(**{**asdict(calibrated), "profile_hash": calibrated.computed_hash()})
        # Node 1 has degree two: ±3 opinion units must be ±6 terminal-score
        # units.  Using a first-turn or raw-w standard deviation would fail.
        graph = board(
            {1: (0.0, "和平", 2), 2: (0.0, "中立", 0), 3: (0.0, "中立", 0)},
            [(1, 2), (1, 3)],
        )
        plan = StructuralPlanner(calibrated, score_fn=degree_weighted).plan(
            graph, 2.0, 1, PolicyMode.B3_SINGLE_STRUCTURE
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.persuasion_actions[0].target_node_1, 1)
        self.assertEqual(plan.risk, 6.0)


if __name__ == "__main__":
    unittest.main()

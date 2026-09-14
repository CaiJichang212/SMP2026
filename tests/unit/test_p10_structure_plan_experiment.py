"""Tests for unrestricted complete structural-plan search."""

import unittest
from unittest.mock import patch

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.budget_experiment import BudgetPlan
from starnet.policy.candidates import Candidate
from starnet.policy.p10_structure_plan_experiment import (
    FullStructurePlan, _legal_structures, choose_full_plan,
)
from starnet.policy.cmg import PredictiveState


def board_fixture() -> Blackboard:
    board = Blackboard(node_count=4)
    weights = (-20.0, -15.0, 4.0, 8.0)
    edges = {1: [2, 3], 2: [1, 4], 3: [1, 4], 4: [2, 3]}
    for node_id, weight in enumerate(weights, 1):
        board.record_scan(node_id, {
            "w": weight,
            "persona": "和平",
            "comm_left": 3,
            "neighbors": edges[node_id],
        })
    return board


class P10StructurePlanTests(unittest.TestCase):
    def test_root_domain_includes_same_sign_cut_and_positive_shield(self):
        board = board_fixture()
        actions = _legal_structures(PredictiveState.from_blackboard(board), 20.0, ())
        self.assertIn(Action("cut", 1, target_node_2=2), actions)
        self.assertIn(Action("shield", 3), actions)

    def test_cut_then_incident_shield_is_excluded_as_waste(self):
        board = board_fixture()
        state = PredictiveState.from_blackboard(board)
        cut = Action("cut", 1, target_node_2=2)
        actions = _legal_structures(state.apply(cut), 17.0, (cut,))
        self.assertNotIn(Action("shield", 1), actions)
        self.assertNotIn(Action("shield", 2), actions)

    def test_complete_plan_can_pass_when_baseline_first_action_cannot_represent_it(self):
        board = board_fixture()
        baseline = Action("comm", 4, prompt_id=1)
        structures = (Action("cut", 1, target_node_2=2), Action("cut", 3, target_node_2=4))
        persuasion = (Action("comm", 4, prompt_id=1),)
        plan = FullStructurePlan(structures, persuasion, 120.0, 100.0, 8, 20, 0.01)
        ranked = [Candidate("baseline", baseline, 0, 1.0, 0.5, "test")]

        def rollout(_board, _budget, _observed, actions, _steps, *, scenario, salt):
            return 120.0 if actions == plan.structure_actions else 100.0

        with patch("starnet.policy.p10_structure_plan_experiment._greedy_candidates",
                   return_value=ranked), \
             patch("starnet.policy.p10_structure_plan_experiment.search_full_structure_plan",
                   return_value=plan), \
             patch("starnet.policy.p10_structure_plan_experiment._rollout_prefix",
                   side_effect=rollout):
            decision = choose_full_plan(
                board, 20.0, {}, remaining_steps=4, salt="a" * 64,
                max_structures=2, beam_width=4,
            )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.actions, plan.structure_actions)
        self.assertEqual(decision.rollouts, 26)


if __name__ == "__main__":
    unittest.main()

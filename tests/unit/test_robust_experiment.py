"""Public-fact and paired-budget checks for the P7 experiment."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.budget_experiment import BudgetPlan
from starnet.policy.cmg import PredictiveState
from starnet.policy.robust_experiment import assess_structure


def two_node_board(negative: float) -> Blackboard:
    board = Blackboard(node_count=2)
    board.record_scan(1, {"w": negative, "persona": "暴力", "comm_left": 3, "neighbors": [2]})
    board.record_scan(2, {"w": 10.0, "persona": "和平", "comm_left": 3, "neighbors": [1]})
    return board


class RobustExperimentTests(unittest.TestCase):
    def test_frozen_modes_compare_the_same_budget_tail(self) -> None:
        board = two_node_board(-42.0)
        proposal = BudgetPlan(0.0, (Action("shield", 1),))
        before = board.snapshot()
        with patch.object(PredictiveState, "to_blackboard", side_effect=AssertionError("prediction leaked")):
            strict = assess_structure(board, 5.0, 2, {}, proposal, mode="strict")
            bounded = assess_structure(board, 5.0, 2, {}, proposal, mode="bounded")
        self.assertEqual(strict.deltas, bounded.deltas)
        self.assertAlmostEqual(strict.deltas[0], 36.0)
        self.assertAlmostEqual(strict.deltas[1], 16.5)
        self.assertAlmostEqual(strict.deltas[2], -3.0)
        self.assertFalse(strict.accepted)
        self.assertTrue(bounded.accepted)
        self.assertEqual(board.snapshot(), before)

    def test_observed_first_response_overrides_all_scenarios(self) -> None:
        board = two_node_board(-42.0)
        proposal = BudgetPlan(0.0, (Action("shield", 1),))
        observed = assess_structure(board, 5.0, 2, {2: 6.0}, proposal, mode="strict")
        unobserved = assess_structure(board, 5.0, 2, {}, proposal, mode="strict")
        self.assertNotEqual(observed.deltas, unobserved.deltas)
        self.assertGreater(observed.deltas[2], unobserved.deltas[2])

    def test_missing_structure_or_budget_fails_closed(self) -> None:
        board = two_node_board(-100.0)
        self.assertFalse(assess_structure(board, 5.0, 2, {}, BudgetPlan(0.0, (Action("comm", 2, prompt_id=1),)), mode="strict").accepted)
        self.assertFalse(assess_structure(board, 4.0, 2, {}, BudgetPlan(0.0, (Action("shield", 1),)), mode="strict").accepted)
        with self.assertRaises(ValueError):
            assess_structure(board, 5.0, 2, {2: float("nan")}, BudgetPlan(0.0, (Action("shield", 1),)), mode="strict")


if __name__ == "__main__":
    unittest.main()

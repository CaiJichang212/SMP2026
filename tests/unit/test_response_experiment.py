"""Regression coverage for the isolated public-response experiment."""

from __future__ import annotations

import unittest

from starnet.model.blackboard import Blackboard
from starnet.policy.response_experiment import PublicResponseCalibrator, ResponseBudgetPlanner


def board() -> Blackboard:
    value = Blackboard(node_count=3)
    value.record_scan(1, {"w": 0.0, "persona": "和平", "comm_left": 3, "neighbors": [2]})
    value.record_scan(2, {"w": 0.0, "persona": "中立", "comm_left": 3, "neighbors": [1, 3]})
    value.record_scan(3, {"w": 0.0, "persona": "暴力", "comm_left": 3, "neighbors": [2]})
    return value


class ResponseExperimentTests(unittest.TestCase):
    def test_fixed_prior_does_not_transfer_one_nodes_response_to_untried_nodes(self) -> None:
        planner = ResponseBudgetPlanner(prior_mode="fixed")
        self.assertTrue(planner.observe_success(1, "和平", 0.0, 30.0, 1))
        value = board()
        value.nodes[1].comm_left = 2
        candidate = planner.next_choice(value, 10.0)
        self.assertIsNotNone(candidate)
        # Node 2 has higher scanned influence, but its untried estimate stays
        # at the population prior rather than inheriting node 1's 30-point delta.
        self.assertEqual(candidate.action.target_node_1, 2)  # type: ignore[union-attr]
        self.assertEqual(candidate.source, "fixed")  # type: ignore[union-attr]

    def test_public_first_response_unlocks_only_its_diminished_repeat_slots(self) -> None:
        value = board()
        planner = ResponseBudgetPlanner()
        self.assertTrue(planner.observe_success(2, "中立", 0.0, 40.0, 1))
        value.nodes[2].comm_left = 2
        candidate = planner.next_choice(value, 10.0)
        self.assertEqual(candidate.action.target_node_1, 2)  # type: ignore[union-attr]
        self.assertEqual(candidate.turn, 2)  # type: ignore[union-attr]
        self.assertEqual(candidate.expected_delta, 20.0)  # type: ignore[union-attr]
        self.assertEqual(candidate.source, "own_first_response")  # type: ignore[union-attr]

    def test_persona_calibration_is_shrunk_and_uses_only_public_records(self) -> None:
        calibrator = PublicResponseCalibrator()
        self.assertTrue(calibrator.record_first(1, "和平", 3.0, 33.0))
        self.assertFalse(calibrator.record_first(1, "和平", 33.0, 44.0))
        self.assertAlmostEqual(calibrator.estimate_first("和平", "persona_shrunk"), (3 * 12.75 + 30.0) / 4)
        self.assertEqual(calibrator.estimate_first("暴力", "persona_shrunk"), 12.75)

    def test_budget_below_communication_cost_has_no_choice(self) -> None:
        self.assertIsNone(ResponseBudgetPlanner().next_choice(board(), 1.5))


if __name__ == "__main__":
    unittest.main()

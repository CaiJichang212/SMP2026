from __future__ import annotations

import unittest
from unittest.mock import patch

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.rollout_experiment import _rollout, choose_rollout_action


def board_for_test():
    board = Blackboard(node_count=3)
    weights = (-30.0, 8.0, 12.0)
    for node_id, weight in enumerate(weights, 1):
        board.record_scan(node_id, {
            "w": weight, "persona": "暴力" if node_id == 1 else "和平",
            "comm_left": 3, "neighbors": [other for other in range(1, 4) if other != node_id],
        })
    return board


class RolloutExperimentTests(unittest.TestCase):
    def test_unknown_response_is_revealed_after_first_simulated_action(self):
        board = board_for_test()
        calls = []

        def no_more_candidates(projected, budget, observed):
            calls.append((budget, dict(observed)))
            return []

        with patch("starnet.policy.rollout_experiment._greedy_candidates", side_effect=no_more_candidates), \
             patch("starnet.policy.rollout_experiment._scenario_factor", return_value=1.5):
            _rollout(board, 4, {}, Action("comm", 2, prompt_id=1), 2,
                     scenario=0, scenario_count=3)
        self.assertEqual(calls, [(2.0, {2: 22.5})])
        self.assertEqual(board.nodes[2].w, 8.0)
        self.assertEqual(board.nodes[2].comm_left, 3)

    def test_rollout_never_records_hypotheses_as_blackboard_facts(self):
        board = board_for_test()
        with patch.object(Blackboard, "record_scan", side_effect=AssertionError("hypothetical scan")), \
             patch.object(Blackboard, "record_communication", side_effect=AssertionError("hypothetical comm")), \
             patch("starnet.policy.cmg.PredictiveState.to_blackboard",
                   side_effect=AssertionError("hypothetical board")):
            _rollout(board, 4, {}, Action("comm", 2, prompt_id=1), 2,
                     scenario=0, scenario_count=1)

    def test_known_response_is_fixed_in_every_scenario(self):
        board = board_for_test()
        board.nodes[2].comm_left = 2
        with patch("starnet.policy.rollout_experiment._scenario_factor") as sample:
            first = _rollout(board, 2, {2: 9.0}, Action("comm", 2, prompt_id=1), 1,
                             scenario=0, scenario_count=3)
            last = _rollout(board, 2, {2: 9.0}, Action("comm", 2, prompt_id=1), 1,
                            scenario=2, scenario_count=3)
        sample.assert_not_called()
        self.assertEqual(first, last)

    def test_decision_has_legal_first_action_and_does_not_mutate_board(self):
        board = board_for_test()
        original = board.snapshot()
        decision = choose_rollout_action(board, 9.0, {}, remaining_steps=4,
                                         scenario_count=1, include_budget_plan=False)
        self.assertIn(decision.action, decision.compared_actions)
        self.assertLessEqual(len(decision.compared_actions), 3)
        self.assertEqual(board.snapshot(), original)

    def test_invalid_scenario_count_fails_closed(self):
        with self.assertRaises(ValueError):
            choose_rollout_action(board_for_test(), 5, {}, remaining_steps=2,
                                  scenario_count=4)


if __name__ == "__main__":
    unittest.main()

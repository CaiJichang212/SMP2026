"""Bounded replay checks for P8 failure attribution."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from scripts.attribute_p8_failures import (
    _forced_then_public_greedy, _seed_for, attribute_case,
)
from scripts.run_local_policy_matrix import LocalPublicEnvironment
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.rollout_experiment import RolloutDecision


def small_seed() -> dict:
    return {
        "global_setting": {"max_budget": 8.0, "max_api_calls": 20},
        "original_total": -10.0,
        "nodes": [
            {"id": 1, "w": -20.0, "persona": "暴力", "r": 1.0, "comm_left": 3},
            {"id": 2, "w": 10.0, "persona": "和平", "r": 1.0, "comm_left": 3},
        ],
        "edges": [[1, 2]],
        "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
    }


class P8FailureAttributionTests(unittest.TestCase):
    def test_replay_forces_one_action_then_uses_public_greedy(self) -> None:
        result = _forced_then_public_greedy(
            small_seed(), (), Action("shield", 1), LocalPublicEnvironment,
        )
        self.assertEqual(result["actions"]["scan"], 2)
        self.assertEqual(result["actions"]["shield"], 1)
        self.assertGreaterEqual(result["remaining_budget"], 0.0)
        self.assertLessEqual(result["steps"], 117)

    def test_known_cohort_guard_rejects_future_repetition(self) -> None:
        with self.assertRaisesRegex(ValueError, "601"):
            _seed_for(("lollipop", 601, "new"))

    @patch("scripts.attribute_p8_failures.run_rollout_search")
    @patch("scripts.attribute_p8_failures.run_variant")
    @patch("scripts.attribute_p8_failures._forced_then_public_greedy")
    @patch("scripts.attribute_p8_failures.choose_rollout_action")
    @patch("scripts.attribute_p8_failures._replay_prefix")
    @patch("scripts.attribute_p8_failures._seed_for", return_value={"nodes": [{}, {}]})
    def test_nonnegative_first_action_but_negative_episode_is_replanning(
        self, _seed, replay, choose, forced, baseline, rollout,
    ) -> None:
        board = Blackboard(node_count=2)
        board.record_scan(1, {"w": -2.0, "persona": "暴力", "comm_left": 3, "neighbors": [2]})
        board.record_scan(2, {"w": 2.0, "persona": "和平", "comm_left": 3, "neighbors": [1]})
        env = Mock()
        env.get_remaining_budget.return_value = 7.0
        replay.return_value = (env, board, {}, 2)
        candidate_action = Action("shield", 1)
        baseline_action = Action("comm", 2, prompt_id=1)
        choose.return_value = RolloutDecision(
            candidate_action, baseline_action, (3.0,),
            (baseline_action, candidate_action), 2,
        )
        forced.side_effect = [
            {"score": 12.0, "remaining_budget": 0.0, "steps": 4, "actions": {}},
            {"score": 10.0, "remaining_budget": 0.0, "steps": 4, "actions": {}},
        ]
        baseline.return_value = {"score": 10.0}
        rollout.return_value = {"score": 9.0}
        result = attribute_case(("er_balanced", 402, "existing"))
        self.assertEqual(result["actual_counterfactual_gain"], 2.0)
        self.assertEqual(result["full_delta"], -1.0)
        self.assertEqual(result["replanning_residual"], -3.0)
        self.assertFalse(result["first_action_response_model_error"])
        self.assertTrue(result["additional_replanning_loss"])
        self.assertEqual(result["attribution"], "additional_replanning_loss")
        self.assertEqual(result["policy_hidden_response_inputs"], [])


if __name__ == "__main__":
    unittest.main()

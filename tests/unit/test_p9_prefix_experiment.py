"""Tests for the development-only committed-prefix experiment."""

import unittest
from unittest.mock import patch

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.candidates import Candidate
from starnet.policy.p9_prefix_experiment import _rollout_prefix, choose_prefix_action
from starnet.policy.p8_experiment import P8Decision


def board_fixture() -> Blackboard:
    board = Blackboard(node_count=4)
    weights = (-30.0, -12.0, 8.0, 14.0)
    for node_id, weight in enumerate(weights, 1):
        board.record_scan(node_id, {
            "w": weight,
            "persona": "暴力" if weight < 0 else "和平",
            "comm_left": 3,
            "neighbors": [other for other in range(1, 5) if other != node_id],
        })
    return board


class P9PrefixExperimentTests(unittest.TestCase):
    def test_predicted_full_prefix_never_mutates_blackboard(self):
        board = board_fixture()
        before = board.snapshot()
        score = _rollout_prefix(
            board,
            12.0,
            {},
            (Action("shield", 1), Action("shield", 2)),
            3,
            scenario=1,
            salt="a" * 64,
        )
        self.assertIsInstance(score, float)
        self.assertEqual(board.snapshot(), before)

    def test_full_prefix_can_pass_when_first_action_has_no_value(self):
        board = board_fixture()
        baseline = Action("comm", 3, prompt_id=1)
        first = Action("shield", 1)
        second = Action("shield", 2)
        fallback = P8Decision(
            baseline, baseline, "public_greedy", (baseline,), (), 0.0, 0.0, 7,
        )

        def rollout(_board, _budget, _observed, sequence, _steps, *, scenario, salt):
            if sequence == (first, second):
                return 102.0
            return 100.0

        with patch("starnet.policy.p9_prefix_experiment.choose_p8_action", return_value=fallback), \
             patch("starnet.policy.p9_prefix_experiment.structural_prefix", return_value=(first, second)), \
             patch("starnet.policy.p9_prefix_experiment._rollout_prefix", side_effect=rollout):
            first_decision = choose_prefix_action(
                board, 12.0, {}, remaining_steps=3, salt="b" * 64, mode="first",
            )
            full_decision = choose_prefix_action(
                board, 12.0, {}, remaining_steps=3, salt="b" * 64, mode="full",
            )
        self.assertFalse(first_decision.accepted)
        self.assertEqual(first_decision.actions, (baseline,))
        self.assertTrue(full_decision.accepted)
        self.assertEqual(full_decision.actions, (first, second))
        self.assertEqual(len(full_decision.selection_deltas), 5)
        self.assertEqual(len(full_decision.audit_deltas), 8)
        self.assertGreaterEqual(full_decision.rollouts, fallback.rollouts)

    def test_rejected_prefix_preserves_bounded_p8_fallback(self):
        board = board_fixture()
        fallback_action = Action("shield", 1)
        fallback = P8Decision(
            fallback_action, Action("comm", 3, prompt_id=1), "p7_budget_structure",
            (), (2.0,) * 5, 2.0, 2.0, 9,
        )
        prefix = (Action("shield", 2), Action("shield", 3))

        def rollout(_board, _budget, _observed, sequence, _steps, *, scenario, salt):
            return 99.0 if sequence == prefix else 100.0

        with patch("starnet.policy.p9_prefix_experiment.choose_p8_action", return_value=fallback), \
             patch("starnet.policy.p9_prefix_experiment.structural_prefix", return_value=prefix), \
             patch("starnet.policy.p9_prefix_experiment._rollout_prefix", side_effect=rollout):
            decision = choose_prefix_action(
                board, 12.0, {}, remaining_steps=3, salt="e" * 64, mode="full",
            )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.actions, (fallback_action,))
        self.assertEqual(decision.baseline_action, fallback_action)

    def test_prefix_rollout_separates_censored_visible_and_latent_response(self):
        board = Blackboard(node_count=1)
        board.record_scan(1, {
            "w": -110.0, "persona": "和平", "comm_left": 3, "neighbors": [],
        })

        def repeat(projected, budget, observed):
            node = projected.nodes[1]
            if not node.comm_left:
                return []
            turn = 4 - node.comm_left
            action = Action("comm", 1, prompt_id=1)
            return [Candidate(f"comm:1:{turn}", action, 0, 1.0, 1.0, "test")]

        with patch("starnet.policy.p9_prefix_experiment._scenario_factor", return_value=0.2), \
             patch("starnet.policy.p9_prefix_experiment._greedy_candidates", side_effect=repeat):
            score = _rollout_prefix(
                board, 20.0, {}, (Action("comm", 1, prompt_id=1),), 3,
                scenario=1, salt="f" * 64,
            )
        self.assertEqual(score, -97.75)
        self.assertEqual(board.nodes[1].w, -110.0)

    def test_illegal_second_prefix_action_is_rejected(self):
        board = board_fixture()
        with self.assertRaisesRegex(ValueError, "illegal action"):
            _rollout_prefix(
                board,
                12.0,
                {},
                (Action("shield", 1), Action("shield", 1)),
                3,
                scenario=1,
                salt="c" * 64,
            )


if __name__ == "__main__":
    unittest.main()

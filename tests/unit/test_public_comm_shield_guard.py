"""Regression coverage for the opt-in public comm/shield guard."""

from __future__ import annotations

import unittest

from starnet.model.blackboard import Blackboard
from starnet.policy.structural import ExperimentalPublicGreedyPlanner


def _board() -> Blackboard:
    board = Blackboard()
    board.record_scan(1, {"w": -40.0, "persona": "暴力", "comm_left": 3, "neighbors": [2, 3]})
    board.record_scan(2, {"w": 10.0, "persona": "和平", "comm_left": 3, "neighbors": [1]})
    board.record_scan(3, {"w": 10.0, "persona": "和平", "comm_left": 3, "neighbors": [1]})
    return board


class PublicCommShieldGuardTests(unittest.TestCase):
    def test_opt_in_guard_removes_comm_to_currently_positive_shield_target(self) -> None:
        ordinary = ExperimentalPublicGreedyPlanner(lambda *_: 15.0, min_observed_responses=0)
        guarded = ExperimentalPublicGreedyPlanner(
            lambda *_: 15.0, min_observed_responses=0, defer_comm_if_shieldable=True,
        )
        ordinary_actions = [candidate.action for candidate in ordinary.candidates(_board(), 20.0)]
        guarded_actions = [candidate.action for candidate in guarded.candidates(_board(), 20.0)]
        self.assertTrue(any(action.kind == "comm" and action.target_node_1 == 1 for action in ordinary_actions))
        self.assertFalse(any(action.kind == "comm" and action.target_node_1 == 1 for action in guarded_actions))
        self.assertIn(next(action for action in ordinary_actions if action.kind == "shield"), guarded_actions)


if __name__ == "__main__":
    unittest.main()

"""Public API failure responses keep state and budget accounting aligned."""

from __future__ import annotations

import unittest

from starnet.policy.actions import Action
from starnet.runtime.controller import RuntimeController


class FailureEnvironment:
    def __init__(self) -> None:
        self.budget = 10.0

    def get_remaining_budget(self) -> float:
        return self.budget

    def scan_node(self, node_id: int) -> None:
        return None

    def communicate(self, node_id: int, prompt_id: int) -> None:
        return None

    def cut_link(self, left: int, right: int) -> None:
        self.budget -= 3.0
        return None

    def shield_node(self, node_id: int) -> None:
        self.budget -= 5.0
        return None


class EnvironmentFailureAccountingTests(unittest.TestCase):
    @staticmethod
    def controller() -> tuple[FailureEnvironment, RuntimeController]:
        env = FailureEnvironment()
        controller = RuntimeController(env, node_count=3)
        controller.blackboard.record_scan(
            1, {"w": -2.0, "persona": "暴力", "comm_left": 1, "neighbors": [2]}
        )
        controller.blackboard.record_scan(
            2, {"w": 1.0, "persona": "和平", "comm_left": 1, "neighbors": [1]}
        )
        return env, controller

    def test_failed_cut_and_shield_refresh_the_debited_public_budget(self) -> None:
        for action, candidate_id, expected_budget in (
            (Action("cut", 1, target_node_2=2), "cut:1-2", 7.0),
            (Action("shield", 1), "shield:1", 5.0),
        ):
            with self.subTest(action=action.kind):
                env, controller = self.controller()

                self.assertFalse(controller._attempt_action(action, candidate_id, 10.0))

                self.assertEqual(env.get_remaining_budget(), expected_budget)
                self.assertEqual(controller.blackboard.budget_units, int(expected_budget * 2))
                self.assertIn(1, controller.blackboard.nodes)
                self.assertIn((1, 2), controller.blackboard.edges)

    def test_failed_scan_and_communication_do_not_debit_public_budget(self) -> None:
        env, controller = self.controller()

        self.assertFalse(controller._attempt_action(Action("comm", 2, prompt_id=1), "comm:2:1", 10.0))
        self.assertEqual(env.get_remaining_budget(), 10.0)
        self.assertEqual(controller.blackboard.budget_units, 20)
        self.assertEqual(controller.blackboard.nodes[2].comm_left, 1)

        # A None scan is a successful public observation that the requested ID
        # is unavailable; it is recorded without a resource debit.
        self.assertTrue(controller._attempt_action(Action("scan", 3), "scan:3", 10.0))
        self.assertEqual(env.get_remaining_budget(), 10.0)
        self.assertEqual(controller.blackboard.budget_units, 20)
        self.assertIn(3, controller.blackboard.nonexistent_ids)


if __name__ == "__main__":
    unittest.main()

import unittest

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action


class ActionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.board = Blackboard()
        self.board.record_scan(1, {"w": 3, "persona": "和平", "comm_left": 1, "neighbors": [2]})
        self.board.record_scan(2, {"w": -4, "persona": "暴力", "comm_left": 3, "neighbors": [1]})

    def test_communication_requires_known_node_remaining_quota_and_valid_prompt(self) -> None:
        self.assertTrue(is_legal_action(Action("comm", 1, prompt_id=1), self.board, 2.0))
        self.assertFalse(is_legal_action(Action("comm", 1, prompt_id=4), self.board, 2.0))
        self.assertFalse(is_legal_action(Action("comm", 1, prompt_id=1), self.board, 1.9))

    def test_cut_requires_known_edge(self) -> None:
        self.assertTrue(is_legal_action(Action("cut", 2, target_node_2=1), self.board, 3.0))
        self.assertFalse(is_legal_action(Action("cut", 1, target_node_2=9), self.board, 3.0))

    def test_repeat_scan_is_rejected(self) -> None:
        self.assertFalse(is_legal_action(Action("scan", 1), self.board, 0.5))
        self.assertTrue(is_legal_action(Action("scan", 3), self.board, 0.5))


if __name__ == "__main__":
    unittest.main()

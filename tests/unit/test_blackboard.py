import unittest

from starnet.model.blackboard import Blackboard


class BlackboardTests(unittest.TestCase):
    def test_scan_preserves_environment_comm_left_and_normalizes_edges(self) -> None:
        board = Blackboard()
        changed = board.record_scan(
            3,
            {"w": -2.5, "persona": "暴力", "comm_left": 1, "neighbors": [5, 1]},
        )

        self.assertTrue(changed)
        self.assertEqual(board.nodes[3].comm_left, 1)
        self.assertEqual(board.edges, {(1, 3), (3, 5)})

    def test_scan_keeps_unreported_communication_quota_unknown(self) -> None:
        board = Blackboard()

        board.record_scan(1, {"w": 4, "persona": "和平", "neighbors": []})

        self.assertIsNone(board.nodes[1].comm_left)

    def test_failed_communication_does_not_change_weight(self) -> None:
        board = Blackboard()
        board.record_scan(1, {"w": 4, "persona": "和平", "comm_left": 2, "neighbors": []})

        self.assertFalse(board.record_communication(1, {"status": "error"}))
        self.assertEqual(board.nodes[1].w, 4.0)
        self.assertEqual(board.nodes[1].comm_left, 2)

    def test_successful_shield_removes_incident_edges(self) -> None:
        board = Blackboard()
        board.record_scan(1, {"w": -3, "persona": "暴力", "comm_left": 3, "neighbors": [2]})
        board.record_scan(2, {"w": 1, "persona": "和平", "comm_left": 3, "neighbors": [1]})

        self.assertTrue(board.record_shield(1, True))
        self.assertNotIn(1, board.nodes)
        self.assertEqual(board.edges, set())
        self.assertIn(1, board.dead_nodes)


if __name__ == "__main__":
    unittest.main()

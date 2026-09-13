"""Exercise a real candidate gap rather than mirroring ranking internals."""
import unittest

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.p8_experiment import choose_p8_action, public_board_salt
from starnet.policy.p9_coverage_experiment import (
    choose_coverage_action, excluded_structure_domain,
)


class CoverageTests(unittest.TestCase):
    def board(self):
        board = Blackboard(node_count=3)
        for node, weight in ((1, 100.0), (2, 1.0), (3, 1.0)):
            board.record_scan(node, {"w": weight, "persona": "和平", "comm_left": 3,
                                     "neighbors": [other for other in (1, 2, 3) if other != node]})
        return board

    def test_positive_graph_gate_can_hide_a_robustly_profitable_cut(self):
        board = self.board()
        before = board.snapshot()
        salt = public_board_salt(board)
        baseline = choose_p8_action(board, 3, {}, remaining_steps=1, salt=salt, mode="conservative")
        self.assertEqual(baseline.action.kind, "comm")
        candidate = choose_coverage_action(board, 3, {}, remaining_steps=1, salt=salt)
        self.assertEqual(candidate.action, Action("cut", 2, target_node_2=3))
        self.assertEqual(candidate.baseline_action, baseline.action)
        self.assertGreater(candidate.minimum_delta, 0)
        self.assertGreater(candidate.audit_minimum_delta, 0)
        self.assertEqual(len(candidate.audit_paired_deltas), 8)
        self.assertEqual(board.snapshot(), before)

    def test_candidate_gap_does_not_bypass_resource_legality(self):
        board = self.board()
        self.assertEqual(excluded_structure_domain(board, 2, {}), ())
        for action in excluded_structure_domain(board, 3, {}):
            self.assertTrue(is_legal_action(action, board, 3))


if __name__ == "__main__":
    unittest.main()

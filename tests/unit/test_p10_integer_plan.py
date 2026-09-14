import unittest

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import is_legal_action, action_cost
from starnet.policy.cmg import PredictiveState
from starnet.policy.p8_experiment import _ProjectedBoard
from starnet.policy.p10_integer_plan_experiment import integer_candidates


class IntegerPlanTests(unittest.TestCase):
    def test_joint_model_finds_harmful_node_without_mutating_public_facts(self):
        board = Blackboard(node_count=5)
        for node in range(1, 6):
            board.record_scan(node, {"w": -80.0 if node == 1 else 20.0,
                "persona": "中立", "comm_left": 3,
                "neighbors": [other for other in range(1, 6) if other != node]})
        before = board.snapshot()
        candidates = integer_candidates(board, 12, dict.fromkeys(range(1, 6), 0.0), 10)
        self.assertTrue(candidates)
        self.assertEqual([action.target_node_1 for action in candidates[0].shields], [1])
        self.assertAlmostEqual(candidates[0].predicted_score, 80.0)
        for plan in candidates:
            state = PredictiveState.from_blackboard(board)
            budget = 12
            for action in plan.shields:
                self.assertTrue(is_legal_action(action, _ProjectedBoard.from_state(state, 5), budget))
                state = state.apply(action)
                budget -= action_cost(action)
        self.assertEqual(board.snapshot(), before)


if __name__ == "__main__":
    unittest.main()

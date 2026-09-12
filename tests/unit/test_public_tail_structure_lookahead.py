"""Contract checks for the local public tail-lookahead experiment."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.run_public_tail_structure_lookahead import _project_comm_tail
from starnet.model.blackboard import Blackboard
from starnet.policy.cmg import PredictiveState


class PublicTailStructureLookaheadTests(unittest.TestCase):
    def test_projection_never_materializes_predictions_in_blackboard(self) -> None:
        board = Blackboard(node_count=2)
        board.record_scan(1, {"w": 0.0, "persona": "和平", "comm_left": 3, "neighbors": [2]})
        board.record_scan(2, {"w": 0.0, "persona": "中立", "comm_left": 3, "neighbors": [1]})
        state = PredictiveState.from_blackboard(board)

        with patch.object(
            PredictiveState,
            "to_blackboard",
            side_effect=AssertionError("prediction entered Blackboard"),
        ):
            score = _project_comm_tail(
                state,
                4.0,
                lambda node_id, _node, turn: float(node_id * (4 - turn)),
            )

        self.assertGreater(score, 0.0)
        self.assertEqual(board.nodes[1].w, 0.0)
        self.assertEqual(board.nodes[1].comm_left, 3)
        self.assertEqual(board.nodes[2].w, 0.0)
        self.assertEqual(board.nodes[2].comm_left, 3)


if __name__ == "__main__":
    unittest.main()

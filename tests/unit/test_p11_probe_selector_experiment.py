"""Selection-only tests for the P11 high-influence probe experiment."""

import unittest

from starnet.model.blackboard import Blackboard
from starnet.runtime.p11_probe_selector_experiment import (
    select_high_influence_prompt_probe_nodes,
)


class P11ProbeSelectorExperimentTests(unittest.TestCase):
    def test_high_component_influence_wins_with_same_eligibility(self):
        board = Blackboard(node_count=5)
        data = {
            1: (1.0, "和平", [2, 3, 4, 5]),
            2: (0.0, "和平", [1]),
            3: (-2.0, "中立", [1]),
            4: (70.0, "和平", [1]),
            5: (3.0, "暴力", [1]),
        }
        for node_id, (weight, persona, neighbors) in data.items():
            board.record_scan(node_id, {
                "w": weight, "persona": persona, "comm_left": 3,
                "neighbors": neighbors,
            })
        self.assertEqual(select_high_influence_prompt_probe_nodes(
            board, max_probe_budget=6.0, max_nodes=1,
        ), (1,))

    def test_budget_and_stable_boundary_filter_match_frozen_limits(self):
        board = Blackboard(node_count=3)
        for node_id, weight in ((1, 0.0), (2, 60.0), (3, -60.0)):
            board.record_scan(node_id, {
                "w": weight, "persona": "和平", "comm_left": 3, "neighbors": [],
            })
        self.assertEqual(select_high_influence_prompt_probe_nodes(
            board, max_probe_budget=5.9,
        ), ())
        self.assertEqual(select_high_influence_prompt_probe_nodes(
            board, max_probe_budget=6.0,
        ), (1,))


if __name__ == "__main__":
    unittest.main()

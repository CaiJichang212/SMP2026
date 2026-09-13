from __future__ import annotations

import unittest

from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p9_distribution_validation import LoggedEnvironment


def seed(weight: float, response: float):
    return {
        "global_setting": {"max_budget": 100.0, "max_api_calls": 120},
        "original_total": weight,
        "nodes": [
            {"id": 1, "w": weight, "persona": "中立", "r": response, "comm_left": 3},
        ],
        "edges": [],
        "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
    }


class P9DistributionRunnerTests(unittest.TestCase):
    def test_communication_matches_public_per_action_bounds(self) -> None:
        upper = LocalPublicEnvironment(seed(100.0, 1.5))
        self.assertEqual(upper.communicate(1, 1)["new_w"], 100.0)
        self.assertEqual(upper.nodes[1]["w"], 100.0)

        lower = LocalPublicEnvironment(seed(-110.0, 0.2))
        self.assertEqual(lower.communicate(1, 1)["new_w"], -100.0)
        self.assertEqual(lower.nodes[1]["w"], -100.0)
        self.assertEqual(lower.communicate(1, 1)["new_w"], -98.5)

        logged = LoggedEnvironment(seed(-110.0, 0.2))
        logged.communicate(1, 1)
        self.assertEqual(logged.action_log[0]["budget_before"], 100.0)
        self.assertEqual(logged.action_log[0]["budget_after"], 98.0)

    def test_action_log_does_not_expose_hidden_response_factor(self) -> None:
        env = LoggedEnvironment(seed(0.0, 1.5))
        env.scan_node(1)
        env.communicate(1, 1)
        for action in env.action_log:
            self.assertNotIn("r", action)
            result = action["public_result"]
            if isinstance(result, dict):
                self.assertNotIn("r", result)


if __name__ == "__main__":
    unittest.main()

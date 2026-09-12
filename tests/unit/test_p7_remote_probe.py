"""The remote sandbox closes a session when settlement completes."""

import unittest
from unittest.mock import Mock

from scripts.run_p7_remote_probe import PairedEnvironment


class RemoteProbeTests(unittest.TestCase):
    def test_budget_after_settlement_uses_pre_eval_snapshot(self):
        env = object.__new__(PairedEnvironment)
        env.remote = Mock()
        env.shadow = Mock()
        env.remote.get_remaining_budget.return_value = 1.0
        env.shadow.get_remaining_budget.return_value = 1.0
        env.remote.trigger_eval.return_value = 123.0
        env.shadow.evaluate.return_value = 122.99
        env.pre_eval_budget = None
        self.assertEqual(env.evaluate(), 123.0)
        env.remote.get_remaining_budget.side_effect = AssertionError("closed session")
        self.assertEqual(env.get_remaining_budget(), 1.0)
        env.remote.get_remaining_budget.assert_called_once()
        self.assertEqual(env.local_score, 122.99)


if __name__ == "__main__":
    unittest.main()

"""Submission-entry experiment flags must remain explicit and role-scoped."""

from __future__ import annotations

import unittest

from starnet.submission.starnet_model import _runtime_config_for_descriptions


class SubmissionExperimentFlagTests(unittest.TestCase):
    def test_only_commander_flag_enables_public_guard(self) -> None:
        base = {"role": "CommanderAgent", "experimental_policy_mode": "public_greedy"}
        normal = _runtime_config_for_descriptions([base], base)
        guarded_description = {**base, "experimental_public_comm_shield_guard": True}
        enabled = _runtime_config_for_descriptions([guarded_description], guarded_description)
        unrelated = _runtime_config_for_descriptions(
            [base, {"role": "Observer", "experimental_public_comm_shield_guard": True}], base,
        )
        self.assertFalse(normal.enable_public_comm_shield_guard)
        self.assertTrue(enabled.enable_public_comm_shield_guard)
        self.assertFalse(unrelated.enable_public_comm_shield_guard)


if __name__ == "__main__":
    unittest.main()

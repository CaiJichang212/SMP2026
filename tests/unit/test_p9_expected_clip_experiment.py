"""Tests for the development-only expected-clipped response prior."""

import unittest

from starnet.policy.p9_expected_clip_experiment import expected_clipped_untried_delta


class ExpectedClipExperimentTests(unittest.TestCase):
    def test_closed_form_matches_known_boundary_values(self):
        self.assertAlmostEqual(expected_clipped_untried_delta(90.0, 1), 8.743589743589743)
        self.assertEqual(expected_clipped_untried_delta(80.0, 1), 12.58974358974359)
        self.assertEqual(expected_clipped_untried_delta(77.5, 1), 12.75)
        self.assertEqual(expected_clipped_untried_delta(100.0, 1), 0.0)

    def test_slot_multiplier_is_applied_before_expectation(self):
        self.assertAlmostEqual(expected_clipped_untried_delta(95.0, 2), 4.371794871794871)
        self.assertAlmostEqual(expected_clipped_untried_delta(95.0, 3), 3.1474358974358974)

    def test_experiment_rejects_out_of_bound_opinions(self):
        with self.assertRaises(ValueError):
            expected_clipped_untried_delta(101.0, 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from scripts.run_p11_prior_discount_full import evaluate_gate, rejected_pair, summarize


class P11PriorDiscountFullRunnerTests(unittest.TestCase):
    def test_early_rejection_is_strictly_preregistered(self):
        self.assertFalse(rejected_pair(-10.0))
        self.assertTrue(rejected_pair(-10.000001))
        self.assertTrue(rejected_pair(float("nan")))

    def test_gate_uses_topology_weighting_and_all_amplitudes(self):
        rows = []
        for block_index in range(10):
            for amplitude in ("base", "wide", "close"):
                rows.append({
                    "topology_block": f"block-{block_index}",
                    "amplitude": amplitude,
                    "prompt1_best": True,
                    "paired_gain": 2.0 if block_index < 8 else 0.0,
                })
        summary = summarize(rows)
        self.assertEqual(summary["nonnegative_topology_means"], 10)
        self.assertEqual(summary["nonnegative_amplitude_means"], 3)
        self.assertTrue(evaluate_gate(summary)["passed"])


if __name__ == "__main__":
    unittest.main()

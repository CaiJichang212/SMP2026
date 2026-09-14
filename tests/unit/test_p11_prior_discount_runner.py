from __future__ import annotations

import unittest

from scripts.run_p11_prior_discount import evaluate_gate, paired_summary


class P11PriorDiscountRunnerTests(unittest.TestCase):
    def test_summary_and_preregistered_gate(self):
        rows = []
        families = (
            "er_balanced", "ba_negative_hubs", "ws_peace_majority",
            "sbm_negative_bridges", "sbm_violent_cluster", "three_sparse_components",
        )
        for index, family in enumerate(families):
            rows.append({"family": family, "prompt1_best": True,
                         "paired_gain": 2.0 if index < 4 else -1.0})
        summary = paired_summary(rows)
        self.assertEqual(summary["cases"], 6)
        self.assertEqual(summary["nonnegative_family_means"], 4)
        self.assertFalse(evaluate_gate(summary)["passed"])


if __name__ == "__main__":
    unittest.main()

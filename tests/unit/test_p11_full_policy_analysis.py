from __future__ import annotations

import unittest

from scripts.analyze_p11_full_policy_validation import block_bootstrap, topology_block


class P11FullPolicyAnalysisTests(unittest.TestCase):
    def test_topology_blocks_keep_response_siblings_together(self) -> None:
        self.assertEqual(topology_block("legacy:er_balanced:1:base:x"),
                         "legacy:er_balanced:1")
        self.assertEqual(topology_block("p9:ba_resampled:901:centered:base:x"),
                         "p9:ba_resampled:901")
        self.assertEqual(topology_block("er_resampled:1401:independent:core:x"),
                         "er_resampled:1401")
        self.assertEqual(topology_block("er_resampled:1401:persona_correlated:core:x"),
                         "er_resampled:1401")

    def test_block_bootstrap_is_deterministic_and_block_weighted(self) -> None:
        blocks = {"a": 1.0, "b": 3.0, "c": 5.0}
        first = block_bootstrap(blocks, draws=1000, seed=7)
        self.assertEqual(first, block_bootstrap(blocks, draws=1000, seed=7))
        self.assertLess(first[0], 3.0)
        self.assertGreater(first[1], 3.0)


if __name__ == "__main__":
    unittest.main()

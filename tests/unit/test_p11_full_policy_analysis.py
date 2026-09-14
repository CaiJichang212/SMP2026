from __future__ import annotations

import unittest

from scripts.analyze_p11_full_policy_validation import (
    audit_p11_calibration, block_bootstrap, json_digest, topology_block,
)
from starnet.experiments.seeds import seed_payload
from starnet.policy.prompt_calibration_experiment import PromptCalibrationLedger


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

    def test_calibration_audit_rejects_unreproducible_identification(self) -> None:
        seed = seed_payload("er_balanced", 50, 1)
        seed["prompts"] = {"1": 15.0, "2": 10.0, "3": -5.0}
        # A deliberately incomplete result cannot claim prompt identification.
        result = {"action_log": [], "action_attempts": 0,
                  "host_action_deltas": [0], "action_log_sha256": json_digest([]),
                  "action_failures": 0, "p8_planning_errors": 0,
                  "p11_planning_errors": 0, "p11_errors": 0,
                  "remaining_budget": 100.0, "score": 0.0,
                  "p11_probe_attempts": 0, "p11_probe_successes": 0,
                  "p11_probe_failures": 0, "p11_probe_budget": 0.0,
                  "p11_probe_nodes": [], "p11_selected_prompt_id": 1,
                  "p11_fallback_to_p9": False, "p11_selected_prompt_dispatches": 0,
                  "ledger": {"accepted": [], "censored": [], "failures": [],
                             "confident": False, "calibration_complete": False,
                             "provisional_prompt_ids": [], "calibrated_prompt_ids": [],
                             "normalized_values": {}}}
        with self.assertRaises(ValueError):
            audit_p11_calibration(result, seed, (1,))


if __name__ == "__main__":
    unittest.main()

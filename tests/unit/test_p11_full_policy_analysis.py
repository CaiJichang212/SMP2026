from __future__ import annotations

import json
import unittest

from scripts.analyze_p11_full_policy_validation import (
    audit_p11_calibration, block_bootstrap, json_digest, topology_block,
)
from starnet.experiments.seeds import seed_payload
from starnet.policy.prompt_calibration_experiment import PromptCalibrationLedger
from scripts.run_p9_distribution_validation import LoggedEnvironment


class P11FullPolicyAnalysisTests(unittest.TestCase):
    def calibration_fixture(self, *, two_probes=False):
        seed = {
            "global_setting": {"max_budget": 100.0, "max_api_calls": 120},
            "original_total": 95.0, "edges": [],
            "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
            "nodes": [{"id": node, "w": 95.0 if node == 11 else 0.0,
                       "r": 0.0 if two_probes and node == 2 else 1.0,
                       "persona": "和平" if node in (2, 10) else "暴力",
                       "comm_left": 3} for node in range(1, 51)],
        }
        env = LoggedEnvironment(seed)
        for node in range(1, 51):
            env.scan_node(node)
        ledger = PromptCalibrationLedger()
        for node in ((2, 10) if two_probes else (2,)):
            before = 0.0
            for turn, prompt in enumerate((1, 2, 3), 1):
                new_w = env.communicate(node, prompt)["new_w"]
                ledger.observe_success(node, prompt, turn, before, new_w)
                before = new_w
        if not two_probes:
            for node in (10, 10, 11, 12):
                env.communicate(node, 1)
        probes = 6 if two_probes else 3
        result = {
            "action_log": env.action_log, "action_attempts": len(env.action_log),
            "host_action_deltas": [1] * len(env.action_log),
            "action_log_sha256": json_digest(env.action_log), "action_failures": 0,
            "p8_planning_errors": 0, "p11_planning_errors": 0, "p11_errors": 0,
            "remaining_budget": env.get_remaining_budget(), "score": env.evaluate(),
            "p11_probe_attempts": probes, "p11_probe_successes": probes,
            "p11_probe_failures": 0, "p11_probe_budget": 2.0 * probes,
            "p11_probe_nodes": [2, 10], "p11_selected_prompt_id": 1,
            "p11_fallback_to_p9": False,
            "p11_selected_prompt_dispatches": 0 if two_probes else 3,
            "p11_selected_prompt_observations": {} if two_probes else {"10": 15.0, "12": 15.0},
            "p11_selected_response_censored": [] if two_probes else [{
                "node_id": 11, "prompt_id": 1, "turn": 1,
                "before": 95.0, "new_w": 100.0, "reason": "opinion_bound",
            }],
            "ledger": {"accepted": ledger.accepted, "censored": ledger.censored,
                       "failures": ledger.failures, "confident": ledger.confident,
                       "calibration_complete": ledger.calibration_complete,
                       "provisional_prompt_ids": list(ledger.provisional_prompt_ids),
                       "calibrated_prompt_ids": list(ledger.calibrated_prompt_ids),
                       "normalized_values": ledger.normalized_values()},
        }
        return seed, json.loads(json.dumps(result))

    def test_repeated_dispatches_are_not_first_observation_attempts(self):
        seed, result = self.calibration_fixture()
        self.assertTrue(audit_p11_calibration(result, seed, (1,)))
        result["p11_selected_prompt_dispatches"] = 4
        with self.assertRaisesRegex(ValueError, "observation-attempt"):
            audit_p11_calibration(result, seed, (1,))

    def test_json_probe_node_key_order_does_not_change_ledger_identity(self):
        seed, result = self.calibration_fixture(two_probes=True)
        self.assertTrue(audit_p11_calibration(result, seed, (1,)))

    def test_reported_selected_response_must_match_public_return(self):
        seed, result = self.calibration_fixture()
        result["p11_selected_prompt_observations"]["10"] = 999.0
        with self.assertRaisesRegex(ValueError, "history disagrees"):
            audit_p11_calibration(result, seed, (1,))

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

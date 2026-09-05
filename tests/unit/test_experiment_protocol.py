"""Offline checks for the manifest plan and result analysis."""

from __future__ import annotations

from pathlib import Path
import unittest

from scripts.analyze_experiments import paired_deltas, require_single_main_cohort, summarize
from scripts.run_experiments import (
    GATE_POLICIES,
    gate_is_stable,
    result_namespace,
    session_spec,
    stable_plan,
    variant_config,
)
from starnet.experiments.seeds import all_seed_payloads


class ExperimentProtocolTests(unittest.TestCase):
    def test_seed_set_is_reproducible_and_has_the_six_requested_networks(self) -> None:
        first = all_seed_payloads()
        second = all_seed_payloads()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 6)
        self.assertTrue(all(len(seed["nodes"]) == 50 for seed in first.values()))
        self.assertTrue(all(seed["global_setting"]["max_budget"] == 100.0 for seed in first.values()))

    def test_stable_dry_run_plan_has_exactly_68_sessions(self) -> None:
        manifest = {
            "main_seeds": list(all_seed_payloads()),
            "variants": [
                "scan_only", "v0_deterministic", "v0_llm3", "risk_loose", "risk_strict",
                "mixed_raw_roi", "communicate_only", "risk_only",
            ],
        }
        plan = stable_plan(manifest)
        self.assertEqual(len(plan), 68)
        self.assertEqual(sum(item["phase"] == "gate" for item in plan), 20)
        self.assertEqual(sum(item["phase"] == "main" for item in plan), 48)
        self.assertEqual(variant_config("v0_llm3").max_llm_calls, 3)
        self.assertEqual(variant_config("v0_deterministic").max_llm_calls, 0)

    def test_v1_session_identity_contains_frozen_profile_identity(self) -> None:
        spec = session_spec(seed_id="seed", variant="v1_cmg", phase="main")
        self.assertIn("calibration_profile_hash", spec["config"])
        self.assertIn("calibration_profile_verified", spec["config"])

    def test_gate_requires_matching_hashes_and_two_percent_spread(self) -> None:
        rows = [
            {
                "variant": policy,
                "final_score": 100.0 + index * 0.1,
                "final_state_hash": policy,
                "scan_snapshot_hash": "scan",
                "comparable": True,
            }
            for policy in GATE_POLICIES
            for index in range(5)
        ]
        stable, spreads = gate_is_stable(rows)
        self.assertTrue(stable)
        self.assertTrue(all(value <= 0.02 for value in spreads.values()))
        rows[0]["final_score"] = 150.0
        self.assertFalse(gate_is_stable(rows)[0])

    def test_gate_rejects_repeatable_but_non_comparable_fixture(self) -> None:
        rows = [
            {
                "variant": policy,
                "final_score": 100.0,
                "final_state_hash": policy,
                "scan_snapshot_hash": "same-wrong-snapshot",
                "comparable": policy != "scan_only",
            }
            for policy in GATE_POLICIES
            for _ in range(5)
        ]
        stable, spreads = gate_is_stable(rows)
        self.assertFalse(stable)
        self.assertEqual(spreads["scan_only"], float("inf"))

    def test_analysis_uses_paired_scan_only_deltas(self) -> None:
        rows = [
            {"phase": "main", "comparable": True, "seed_id": "a", "repetition": 1, "variant": "scan_only", "final_score": 10.0},
            {"phase": "main", "comparable": True, "seed_id": "a", "repetition": 1, "variant": "risk_only", "final_score": 13.0},
            {"phase": "main", "comparable": True, "seed_id": "b", "repetition": 1, "variant": "scan_only", "final_score": 20.0},
            {"phase": "main", "comparable": True, "seed_id": "b", "repetition": 1, "variant": "risk_only", "final_score": 18.0},
        ]
        self.assertEqual(paired_deltas(rows)["risk_only"], {"a": [3.0], "b": [-2.0]})
        self.assertEqual(summarize(rows)["variants"]["risk_only"]["seed_count"], 2)

    def test_analysis_excludes_protocol_or_action_failure_even_if_flagged_comparable(self) -> None:
        rows = [
            {"phase": "main", "comparable": True, "seed_id": "a", "repetition": 1, "variant": "scan_only", "final_score": 10.0},
            {"phase": "main", "comparable": True, "seed_id": "a", "repetition": 1, "variant": "risk_only", "final_score": 13.0, "protocol_error": "RuntimeError"},
            {"phase": "main", "comparable": True, "seed_id": "b", "repetition": 1, "variant": "scan_only", "final_score": 20.0},
            {"phase": "main", "comparable": True, "seed_id": "b", "repetition": 1, "variant": "risk_only", "final_score": 18.0, "action_failures": 1},
        ]
        self.assertEqual(paired_deltas(rows), {})
        self.assertEqual(summarize(rows)["valid_main_sessions"], 2)

    def test_result_namespaces_and_analysis_cohorts_cannot_mix_plans(self) -> None:
        base = self._testMethodName
        self.assertNotEqual(
            result_namespace(Path(base), {"name": "first"}),
            result_namespace(Path(base), {"name": "second"}),
        )
        rows = [
            {"phase": "main", "plan_hash": "plan-a", "matrix_branch": "stable"},
            {"phase": "main", "plan_hash": "plan-b", "matrix_branch": "unstable"},
        ]
        with self.assertRaises(ValueError):
            require_single_main_cohort(rows)


if __name__ == "__main__":
    unittest.main()

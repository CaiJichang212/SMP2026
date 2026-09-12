"""P7 new-topology runner contract checks."""

from __future__ import annotations

from unittest.mock import patch
import unittest

from scripts.run_p7_new_topologies import run_matrix


class P7NewTopologiesRunnerTests(unittest.TestCase):
    @patch("scripts.run_p7_new_topologies.run_rollout")
    @patch("scripts.run_p7_new_topologies.run_robust")
    @patch("scripts.run_p7_new_topologies.run_variant")
    def test_rows_are_paired_and_robust_variants_share_seed_cache(
        self, baseline, robust, rollout,
    ) -> None:
        baseline.return_value = {"score": 10.0, "failures": 0}
        robust.side_effect = lambda seed, mode, plan_cache: {
            "score": 12.0 if mode == "strict_anchor" else 13.0,
            "failures": 0, "remaining_budget": 0.0, "steps": 80,
            "cache_identity": id(plan_cache),
        }
        rollout.return_value = {
            "score": 14.0, "failures": 0, "remaining_budget": 0.0, "steps": 80,
        }
        report = run_matrix(
            repetitions=(301,), strata=("standard",),
            variants=("strict_anchor", "bounded_anchor", "mean"),
            families=("random_tree",),
        )
        self.assertEqual(len(report["rows"]), 3)
        self.assertEqual([row["delta"] for row in report["rows"]], [2.0, 3.0, 4.0])
        self.assertTrue(all(row["r_stratum"] == "standard" for row in report["rows"]))
        self.assertEqual(len({row["seed_sha256"] for row in report["rows"]}), 1)
        self.assertEqual(robust.call_count, 2)
        self.assertIs(robust.call_args_list[0].kwargs["plan_cache"],
                      robust.call_args_list[1].kwargs["plan_cache"])
        self.assertEqual(baseline.call_count, 1)

    @patch("scripts.run_p7_new_topologies.run_rollout")
    @patch("scripts.run_p7_new_topologies.run_robust")
    @patch("scripts.run_p7_new_topologies.run_variant")
    def test_multiple_response_strata_are_summarized_separately(
        self, baseline, robust, rollout,
    ) -> None:
        baseline.return_value = {"score": 10.0, "failures": 0}
        robust.return_value = {"score": 10.0, "failures": 0, "remaining_budget": 0.0, "steps": 80}
        rollout.return_value = {"score": 10.0, "failures": 0, "remaining_budget": 0.0, "steps": 80}
        report = run_matrix(
            repetitions=(301,), strata=("low", "high"), variants=("strict_anchor",),
            families=("random_tree",),
        )
        self.assertEqual(report["summary"], {})
        self.assertEqual(set(report["stratum_summary"]), {"low", "high"})
        self.assertEqual(report["stratum_summary"]["low"]["strict_anchor"]["cases"], 1)


if __name__ == "__main__":
    unittest.main()

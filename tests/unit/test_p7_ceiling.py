"""Independent checks for P7 seed pairing and oracle resource accounting."""

from __future__ import annotations

import unittest

from scripts.diagnose_p7_ceiling import diagnose, persuasion_oracle
from scripts.run_local_policy_matrix import LocalPublicEnvironment
from starnet.experiments.p7_seeds import FAMILIES, R_STRATA, seed_payload


class P7SeedTests(unittest.TestCase):
    def test_generated_seeds_are_legal_deterministic_and_stratified(self) -> None:
        for family in FAMILIES:
            with self.subTest(family=family):
                standard = seed_payload(family, 301)
                self.assertEqual(standard, seed_payload(family, 301))
                self.assertEqual(set(node["id"] for node in standard["nodes"]), set(range(1, 51)))
                self.assertEqual(len(standard["edges"]), len(set(map(tuple, standard["edges"]))))
                self.assertTrue(all(1 <= left < right <= 50 for left, right in standard["edges"]))
                self.assertEqual(standard["global_setting"]["max_budget"], 100.0)
                self.assertNotEqual(standard["edges"], seed_payload(family, 302)["edges"])
                for stratum, (low, high) in R_STRATA.items():
                    other = seed_payload(family, 301, stratum)
                    self.assertEqual(standard["edges"], other["edges"])
                    self.assertEqual(
                        [(node["id"], node["w"], node["persona"]) for node in standard["nodes"]],
                        [(node["id"], node["w"], node["persona"]) for node in other["nodes"]],
                    )
                    self.assertTrue(all(low <= node["r"] <= high for node in other["nodes"]))

    def test_unknown_or_wrong_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            seed_payload("old_family", 301)
        with self.assertRaises(ValueError):
            seed_payload("barbell", 301, node_count=100)


class P7OracleTests(unittest.TestCase):
    def test_oracle_respects_scan_cost_and_decreasing_marginals(self) -> None:
        seed = {
            "global_setting": {"max_budget": 4.0},
            "nodes": [
                {"id": 1, "w": 2.0, "persona": "和平", "r": 1.0, "comm_left": 3},
                {"id": 2, "w": -1.0, "persona": "暴力", "r": 0.1, "comm_left": 3},
            ],
            "edges": [[1, 2]],
            "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
        }
        full_score, full_actions = persuasion_oracle(seed)
        free_score, free_actions = persuasion_oracle(seed, free_scan=True)
        self.assertEqual(full_actions, [1])
        self.assertEqual(free_actions, [1, 1])
        self.assertAlmostEqual(full_score, 16.0)
        self.assertAlmostEqual(free_score, 23.5)

        env = LocalPublicEnvironment(seed)
        for node in (1, 2):
            env.scan_node(node)
        for node in full_actions:
            self.assertEqual(env.communicate(node, 1)["status"], "success")
        self.assertAlmostEqual(env.evaluate(), full_score)

    def test_oracle_starts_from_reported_remaining_slot_and_accepts_json_keys(self) -> None:
        seed = {
            "global_setting": {"max_budget": 2.0},
            "nodes": [{"id": 1, "w": 0.0, "persona": "和平", "r": 1.0, "comm_left": 2}],
            "edges": [],
            "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
        }
        score, actions = persuasion_oracle(seed, free_scan=True)
        self.assertEqual(actions, [1])
        self.assertAlmostEqual(score, 7.5)

    def test_diagnosis_keeps_oracle_and_policy_semantics_distinct(self) -> None:
        result = diagnose(seed_payload("random_tree", 301, "low"))
        self.assertEqual(result["public_greedy_actions"]["scan"], 50)
        self.assertEqual(result["public_greedy_failures"], 0)
        self.assertEqual(result["full_scan_oracle_communications"], 37)
        self.assertEqual(result["free_scan_oracle_communications"], 50)
        self.assertGreaterEqual(
            result["free_scan_fixed_topology_persuasion_oracle"],
            result["full_scan_fixed_topology_persuasion_oracle"],
        )


if __name__ == "__main__":
    unittest.main()

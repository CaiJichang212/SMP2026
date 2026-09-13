"""P8 seed distribution contract checks without running policy cohorts."""

from __future__ import annotations

import unittest

from starnet.experiments.p8_seeds import (
    CONFIRMATION_REPETITIONS,
    DEVELOPMENT_REPETITIONS,
    FAMILIES,
    NEW_FAMILIES,
    OLD_FAMILIES,
    R_STRATA,
    seed_payload,
)


class P8SeedTests(unittest.TestCase):
    def test_family_and_repetition_registry_is_exact(self) -> None:
        self.assertEqual(len(OLD_FAMILIES), 18)
        self.assertEqual(len(NEW_FAMILIES), 4)
        self.assertEqual(len(FAMILIES), 22)
        self.assertEqual(DEVELOPMENT_REPETITIONS, (501, 502, 503))
        self.assertEqual(CONFIRMATION_REPETITIONS, (601, 602, 603, 604, 605))

    def test_new_development_seeds_are_legal_reproducible_and_independent(self) -> None:
        for family in NEW_FAMILIES:
            with self.subTest(family=family):
                seed = seed_payload(family, 501)
                self.assertEqual(seed, seed_payload(family, 501))
                self.assertEqual({node["id"] for node in seed["nodes"]}, set(range(1, 51)))
                self.assertEqual(len(seed["edges"]), len(set(map(tuple, seed["edges"]))))
                self.assertTrue(all(1 <= left < right <= 50 for left, right in seed["edges"]))
                self.assertEqual(seed["global_setting"], {"max_budget": 100.0, "max_api_calls": 120})
                self.assertNotEqual(seed["edges"], seed_payload(family, 502)["edges"])

    def test_response_strata_preserve_public_seed_and_stay_in_range(self) -> None:
        for family in NEW_FAMILIES:
            standard = seed_payload(family, 501)
            public = [(node["id"], node["w"], node["persona"], node["comm_left"])
                      for node in standard["nodes"]]
            for stratum in R_STRATA:
                with self.subTest(family=family, stratum=stratum):
                    seed = seed_payload(family, 501, stratum)
                    self.assertEqual(seed["edges"], standard["edges"])
                    self.assertEqual(public, [(node["id"], node["w"], node["persona"], node["comm_left"])
                                              for node in seed["nodes"]])
                    self.assertTrue(all(0.2 <= node["r"] <= 1.5 for node in seed["nodes"]))
                    if stratum == "low":
                        self.assertTrue(all(node["r"] <= 0.55 for node in seed["nodes"]))
                    if stratum == "high":
                        self.assertTrue(all(node["r"] >= 1.1 for node in seed["nodes"]))

    def test_uniform_wrapper_accepts_each_historical_source(self) -> None:
        for family in ("er_balanced", "grid_lattice", "ring_of_cliques", "random_tree"):
            with self.subTest(family=family):
                seed = seed_payload(family, 501)
                self.assertEqual(len(seed["nodes"]), 50)
                self.assertTrue(all(0.2 <= node["r"] <= 1.5 for node in seed["nodes"]))

    def test_invalid_inputs_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            seed_payload("unknown", 501)
        with self.assertRaises(ValueError):
            seed_payload(NEW_FAMILIES[0], 501, "other")
        with self.assertRaises(ValueError):
            seed_payload(NEW_FAMILIES[0], 501, node_count=100)


if __name__ == "__main__":
    unittest.main()

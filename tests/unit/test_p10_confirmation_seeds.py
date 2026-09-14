from __future__ import annotations

import statistics
import unittest

from starnet.experiments.p10_confirmation_seeds import (
    CONFIRMATION_REPETITIONS, FAMILIES, STRATA, seed_payload,
)
from starnet.experiments.p9_distribution_seeds import seed_payload as p9_seed_payload


class P10ConfirmationSeedTests(unittest.TestCase):
    def test_registry_and_default_closed_gate(self) -> None:
        self.assertEqual(CONFIRMATION_REPETITIONS, (1201, 1202, 1203))
        self.assertEqual(len(FAMILIES) * len(STRATA) * len(CONFIRMATION_REPETITIONS), 48)
        with self.assertRaisesRegex(ValueError, "explicit unlock"):
            seed_payload(FAMILIES[0], 1201, STRATA[0])

    def test_unlocked_seeds_are_legal_reproducible_and_fresh(self) -> None:
        hashes = set()
        for family in FAMILIES:
            first = seed_payload(family, 1201, "independent", allow_confirmation=True)
            self.assertEqual(
                first,
                seed_payload(family, 1201, "independent", allow_confirmation=True),
            )
            self.assertEqual({node["id"] for node in first["nodes"]}, set(range(1, 51)))
            self.assertTrue(all(1 <= left < right <= 50 for left, right in first["edges"]))
            self.assertEqual(len(first["edges"]), len(set(map(tuple, first["edges"]))))
            self.assertNotEqual(
                first["edges"],
                seed_payload(family, 1202, "independent", allow_confirmation=True)["edges"],
            )
            self.assertNotEqual(first, p9_seed_payload(family, 901, "centered_independent"))
            hashes.add(str(first))
        self.assertEqual(len(hashes), len(FAMILIES))

    def test_public_opinions_are_shared_across_strata_and_cannot_reach_cap(self) -> None:
        for family in FAMILIES:
            seeds = {
                stratum: seed_payload(family, 1201, stratum, allow_confirmation=True)
                for stratum in STRATA
            }
            reference = seeds["independent"]
            public = [(node["id"], node["w"], node["persona"], node["comm_left"])
                      for node in reference["nodes"]]
            for seed in seeds.values():
                self.assertEqual(seed["edges"], reference["edges"])
                self.assertEqual(public, [(node["id"], node["w"], node["persona"], node["comm_left"])
                                          for node in seed["nodes"]])
                self.assertTrue(all(-38.0 <= node["w"] <= 30.0 for node in seed["nodes"]))
                self.assertTrue(all(0.2 <= node["r"] <= 1.5 for node in seed["nodes"]))
                self.assertTrue(all(node["w"] + 15.0 * node["r"] * 1.75 < 100.0
                                    for node in seed["nodes"]))

    def test_degree_stress_is_correlated_beyond_persona_model(self) -> None:
        seed = seed_payload("ba_resampled", 1201, "degree_correlated", allow_confirmation=True)
        degree = {node["id"]: 0 for node in seed["nodes"]}
        for left, right in seed["edges"]:
            degree[left] += 1
            degree[right] += 1
        by_id = {node["id"]: node for node in seed["nodes"]}
        ids = sorted(by_id)
        self.assertGreater(statistics.correlation(
            [degree[node_id] for node_id in ids], [by_id[node_id]["r"] for node_id in ids],
        ), 0.9)

    def test_invalid_requests_remain_closed(self) -> None:
        for args in (("unknown", 1201, STRATA[0]),
                     (FAMILIES[0], 1200, STRATA[0]),
                     (FAMILIES[0], 1201, "unknown")):
            with self.assertRaises(ValueError):
                seed_payload(*args, allow_confirmation=True)
        with self.assertRaises(ValueError):
            seed_payload(FAMILIES[0], 1201, STRATA[0], node_count=100,
                         allow_confirmation=True)


if __name__ == "__main__":
    unittest.main()

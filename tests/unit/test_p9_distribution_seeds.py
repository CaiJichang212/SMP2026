from __future__ import annotations

import statistics
import unittest

from starnet.experiments.p9_distribution_seeds import (
    CONFIRMATION_REPETITIONS,
    DEVELOPMENT_REPETITIONS,
    FAMILIES,
    SHIFT_STRATA,
    seed_payload,
)


def _by_id(seed):
    return {node["id"]: node for node in seed["nodes"]}


def _degrees(seed):
    result = {node["id"]: 0 for node in seed["nodes"]}
    for left, right in seed["edges"]:
        result[left] += 1
        result[right] += 1
    return result


class P9DistributionSeedTests(unittest.TestCase):
    def test_registry_and_confirmation_are_closed_by_default(self) -> None:
        self.assertEqual(len(FAMILIES), 4)
        self.assertEqual(len(SHIFT_STRATA), 7)
        self.assertEqual(DEVELOPMENT_REPETITIONS, (901, 902))
        self.assertEqual(CONFIRMATION_REPETITIONS, (1001, 1002, 1003, 1004, 1005))
        with self.assertRaisesRegex(ValueError, "reserved"):
            seed_payload(FAMILIES[0], CONFIRMATION_REPETITIONS[0])

    def test_development_graphs_are_legal_reproducible_and_resampled(self) -> None:
        edge_sets = set()
        for family in FAMILIES:
            for repetition in DEVELOPMENT_REPETITIONS:
                with self.subTest(family=family, repetition=repetition):
                    seed = seed_payload(family, repetition)
                    self.assertEqual(seed, seed_payload(family, repetition))
                    self.assertEqual(seed["global_setting"], {
                        "max_budget": 100.0, "max_api_calls": 120,
                    })
                    self.assertEqual({node["id"] for node in seed["nodes"]}, set(range(1, 51)))
                    self.assertEqual(len(seed["edges"]), len(set(map(tuple, seed["edges"]))))
                    self.assertTrue(all(1 <= left < right <= 50 for left, right in seed["edges"]))
                    self.assertTrue(all(0.2 <= node["r"] <= 1.5 for node in seed["nodes"]))
                    edge_sets.add(tuple(map(tuple, seed["edges"])))
            self.assertNotEqual(
                seed_payload(family, 901)["edges"], seed_payload(family, 902)["edges"],
            )
        self.assertEqual(len(edge_sets), len(FAMILIES) * len(DEVELOPMENT_REPETITIONS))

    def test_strata_share_graph_and_base_personas_but_shift_weights(self) -> None:
        reference = seed_payload("er_resampled", 901)
        reference_nodes = _by_id(reference)
        shifted = {name: seed_payload("er_resampled", 901, name) for name in SHIFT_STRATA}
        for name, seed in shifted.items():
            self.assertEqual(seed["edges"], reference["edges"])
            if name != "saturated_hubs":
                self.assertEqual(
                    {node_id: node["persona"] for node_id, node in _by_id(seed).items()},
                    {node_id: node["persona"] for node_id, node in reference_nodes.items()},
                )
        means = {name: statistics.mean(node["w"] for node in seed["nodes"])
                 for name, seed in shifted.items()}
        spreads = {name: statistics.pstdev(node["w"] for node in seed["nodes"])
                   for name, seed in shifted.items()}
        self.assertLess(means["negative_persona_aligned"], means["centered_independent"])
        self.assertGreater(means["positive_persona_inverse"], means["centered_independent"])
        self.assertGreater(spreads["wide_degree_positive"], spreads["centered_independent"])
        self.assertLess(spreads["compressed_degree_negative"], spreads["centered_independent"])

        near = shifted["near_upper_bound"]
        self.assertTrue(all(80.0 <= node["w"] <= 100.0 for node in near["nodes"]))
        self.assertEqual(
            {node_id: node["persona"] for node_id, node in _by_id(near).items()},
            {node_id: node["persona"] for node_id, node in reference_nodes.items()},
        )

        hubs = shifted["saturated_hubs"]
        degrees = _degrees(hubs)
        highest = sorted(degrees, key=lambda node_id: (-degrees[node_id], node_id))[:10]
        self.assertTrue(all(_by_id(hubs)[node_id]["persona"] == "和平" for node_id in highest))
        self.assertTrue(all(90.0 <= _by_id(hubs)[node_id]["w"] <= 100.0 for node_id in highest))

    def test_response_correlations_match_preregistered_direction(self) -> None:
        aligned = seed_payload("ba_resampled", 901, "negative_persona_aligned")
        inverse = seed_payload("ba_resampled", 901, "positive_persona_inverse")
        aligned_means = {
            persona: statistics.mean(node["r"] for node in aligned["nodes"]
                                     if node["persona"] == persona)
            for persona in ("和平", "中立", "暴力")
        }
        inverse_means = {
            persona: statistics.mean(node["r"] for node in inverse["nodes"]
                                     if node["persona"] == persona)
            for persona in ("和平", "中立", "暴力")
        }
        self.assertGreater(aligned_means["和平"], aligned_means["中立"])
        self.assertGreater(aligned_means["中立"], aligned_means["暴力"])
        self.assertLess(inverse_means["和平"], inverse_means["中立"])
        self.assertLess(inverse_means["中立"], inverse_means["暴力"])

        for stratum, sign in (("wide_degree_positive", 1), ("compressed_degree_negative", -1),
                              ("saturated_hubs", 1)):
            seed = seed_payload("ba_resampled", 901, stratum)
            nodes, degrees = _by_id(seed), _degrees(seed)
            correlation = statistics.correlation(
                [degrees[node_id] for node_id in sorted(nodes)],
                [nodes[node_id]["r"] for node_id in sorted(nodes)],
            )
            self.assertGreater(sign * correlation, 0.9)

    def test_invalid_inputs_are_rejected_without_opening_confirmation(self) -> None:
        with self.assertRaises(ValueError):
            seed_payload("unknown", 901)
        with self.assertRaises(ValueError):
            seed_payload(FAMILIES[0], 901, "unknown")
        with self.assertRaises(ValueError):
            seed_payload(FAMILIES[0], 903)
        with self.assertRaises(ValueError):
            seed_payload(FAMILIES[0], 901, node_count=100)


if __name__ == "__main__":
    unittest.main()

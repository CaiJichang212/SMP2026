from __future__ import annotations

import collections
import unittest

from starnet.experiments.p11_validation_seeds import (
    CONFIRMATION_REPETITIONS, confirmation_edge_assignments,
    development_cases, confirmation_cases,
)


class P11ValidationSeedTests(unittest.TestCase):
    def test_development_is_complete_and_permutation_symmetric(self) -> None:
        rows = list(development_cases())
        self.assertEqual(len(rows), 252)
        counts = collections.Counter(amplitude for _, amplitude, _, _ in rows)
        self.assertEqual(counts, {"base": 84, "wide": 84, "close": 84})
        best_ids = collections.Counter(
            max(range(3), key=lambda index: values[index]) + 1
            for _, _, values, _ in rows
        )
        self.assertEqual(best_ids, {1: 84, 2: 84, 3: 84})

    def test_fresh_confirmation_is_reserved_without_materializing_seeds(self) -> None:
        self.assertEqual(CONFIRMATION_REPETITIONS, (1401, 1402, 1403))
        with self.assertRaisesRegex(ValueError, "reserved"):
            next(confirmation_cases())

    def test_confirmation_case_count_is_declared_without_opening_it(self) -> None:
        core = 4 * 3 * 2 * 2 * 6
        edge = len(confirmation_edge_assignments())
        degree_stress = 4 * 1 * 6
        self.assertEqual(core + edge + degree_stress, 360)

    def test_development_seed_prompt_map_matches_declared_permutation(self) -> None:
        case_id, _, values, seed = next(development_cases())
        self.assertTrue(case_id.startswith("legacy:"))
        self.assertEqual(tuple(seed["prompts"][str(prompt_id)] for prompt_id in (1, 2, 3)),
                         values)
        self.assertEqual(len(seed["nodes"]), 50)

    def test_confirmation_edge_metadata_balances_response_family_and_ids(self) -> None:
        rows = confirmation_edge_assignments()
        self.assertEqual(len(rows), 48)
        by_mode = collections.Counter(row[3] for row in rows)
        self.assertEqual(by_mode, {"tie": 12, "zero": 12, "all_negative": 12, "clip": 12})
        for mode in by_mode:
            selected = [row for row in rows if row[3] == mode]
            self.assertEqual(collections.Counter(row[2] for row in selected),
                             {"independent": 6, "persona_correlated": 6})
            self.assertEqual(collections.Counter(row[0] for row in selected),
                             {"er_resampled": 3, "ba_resampled": 3,
                              "ws_resampled": 3, "sbm_resampled": 3})
        for mode in ("all_negative", "clip"):
            selected = [row[4] for row in rows if row[3] == mode]
            self.assertEqual(len(set(selected)), 6)
            self.assertTrue(all(selected.count(values) == 2 for values in set(selected)))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from scripts.run_p10_combined_confirmation import first_candidate_ranker


class P10CombinedConfirmationRunnerTests(unittest.TestCase):
    def test_mock_ranker_returns_strict_valid_first_candidate(self) -> None:
        decisions = []
        payload = {
            "state_version": 7,
            "candidates": [
                {"candidate_id": "p10-plan:first", "evidence_ids": ["plan-proof"]},
                {"candidate_id": "p9:baseline", "evidence_ids": ["p9-proof"]},
            ],
        }
        self.assertEqual(first_candidate_ranker(payload, decisions), {
            "state_version": 7, "mode": "single_action",
            "candidate_id": "p10-plan:first", "reason_code": "paired_first_candidate",
            "evidence_ids": ["plan-proof"],
        })
        self.assertEqual(decisions[0]["selected_candidate_id"], "p10-plan:first")

    def test_mock_ranker_rejects_empty_or_incomplete_payload(self) -> None:
        for payload in ({"state_version": 1, "candidates": []},
                        {"state_version": 1, "candidates": [{"candidate_id": "x"}]}):
            with self.assertRaises(ValueError):
                first_candidate_ranker(payload)


if __name__ == "__main__":
    unittest.main()

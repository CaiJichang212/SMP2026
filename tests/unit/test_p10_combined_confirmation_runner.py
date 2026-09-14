from __future__ import annotations

import unittest

from scripts.run_p10_combined_confirmation import terminal_gain_ranker


class P10CombinedConfirmationRunnerTests(unittest.TestCase):
    def test_mock_ranker_selects_max_terminal_score(self) -> None:
        decisions = []
        payload = {
            "state_version": 7,
            "candidates": [
                {"candidate_id": "p10-plan:first", "evidence_ids": ["plan-proof"],
                 "score": 9.0, "reason": "P10 COMPLETE"},
                {"candidate_id": "pg:baseline", "evidence_ids": ["pg-proof"],
                 "score": 0.0, "reason": "PG REFERENCE: baseline"},
                {"candidate_id": "p8:proposal", "evidence_ids": ["p8-proof"],
                 "score": 7.0, "reason": "P8 terminal"},
            ],
        }
        self.assertEqual(terminal_gain_ranker(payload, decisions), {
            "state_version": 7, "mode": "single_action",
            "candidate_id": "p10-plan:first", "reason_code": "fixed_mock_ranker",
            "evidence_ids": ["plan-proof"],
        })
        self.assertEqual(decisions[0]["selected_candidate_id"], "p10-plan:first")

    def test_mock_ranker_uses_first_for_ordinary_p9_candidates(self) -> None:
        payload = {"state_version": 1, "candidates": [
            {"candidate_id": "comm:first", "evidence_ids": ["a"],
             "score": 1.0, "reason": "ordinary"},
            {"candidate_id": "comm:second", "evidence_ids": ["b"],
             "score": 99.0, "reason": "ordinary"},
        ]}
        self.assertEqual(terminal_gain_ranker(payload)["candidate_id"], "comm:first")

    def test_mock_ranker_rejects_empty_or_incomplete_payload(self) -> None:
        for payload in ({"state_version": 1, "candidates": []},
                        {"state_version": 1, "candidates": [{"candidate_id": "x"}]}):
            with self.assertRaises(ValueError):
                terminal_gain_ranker(payload)


if __name__ == "__main__":
    unittest.main()

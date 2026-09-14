from __future__ import annotations

import unittest

from scripts.run_p11_full_policy_validation import KnownPromptEnvironment, rank_first


class P11FullPolicyRunnerTests(unittest.TestCase):
    def test_ranker_selects_first_valid_candidate(self) -> None:
        decisions = []
        result = rank_first({"state_version": 4, "candidates": [
            {"candidate_id": "first", "evidence_ids": ["a"], "score": 2.0,
             "roi": 1.0, "reason": "first reason", "action": {"kind": "comm"}},
            {"candidate_id": "second", "evidence_ids": ["b"], "score": 1.0,
             "roi": 0.5, "reason": "second reason", "action": {"kind": "comm"}},
        ]}, decisions)
        self.assertEqual(result["candidate_id"], "first")
        self.assertEqual(decisions[0]["selected_candidate_id"], "first")
        self.assertEqual(decisions[0]["selected_candidate"]["score"], 2.0)

    def test_known_prompt_reference_maps_only_environment_dispatch(self) -> None:
        seed = {"global_setting": {"max_budget": 100.0, "max_api_calls": 120},
                "nodes": [{"id": 1, "w": 0.0, "persona": "中立", "r": 1.0,
                           "comm_left": 3}], "edges": [], "original_total": 0.0,
                "prompts": {"1": 1.0, "2": 9.0, "3": -2.0}}
        env = KnownPromptEnvironment(seed, 2)
        result = env.communicate(1, 1)
        self.assertEqual(result["new_w"], 9.0)
        self.assertEqual(env.action_log[-1]["requested_prompt_id"], 1)
        self.assertEqual(env.action_log[-1]["dispatched_prompt_id"], 2)


if __name__ == "__main__":
    unittest.main()

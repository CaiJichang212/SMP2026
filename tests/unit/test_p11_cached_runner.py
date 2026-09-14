from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from scripts.run_p11_full_policy_cached import run_group
from starnet.experiments.seeds import seed_payload


def fake_result(score=1.0):
    return {"score": score, "action_log": [], "action_log_sha256": "empty",
            "p11_selected_prompt_id": 1}


class P11CachedRunnerTests(unittest.TestCase):
    def test_group_runs_p11_fresh_and_marks_exact_reference_reuse(self) -> None:
        first = seed_payload("er_balanced", 50, 1)
        second = copy.deepcopy(first)
        first["prompts"] = {"1": 15.0, "2": 10.0, "3": -5.0}
        second["prompts"] = {"1": 15.0, "2": -5.0, "3": 10.0}
        cases = (("legacy:er_balanced:1:base:a", "base", (15.0, 10.0, -5.0), first),
                 ("legacy:er_balanced:1:base:b", "base", (15.0, -5.0, 10.0), second))
        snapshot = {"source": "hash"}
        with patch("scripts.run_p11_full_policy_cached.source_snapshot", return_value=snapshot), \
             patch("scripts.run_p11_full_policy_cached.run_source", side_effect=lambda seed, mode: fake_result()), \
             patch("scripts.run_p11_full_policy_cached.run_archive", side_effect=lambda seed, known_prompt_id=None: {
                 **fake_result(), "known_prompt_id": known_prompt_id,
             }):
            rows = run_group((cases, snapshot))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["arms"]["p11"]["reference_cache"]["kind"],
                         "not_cacheable_p11_execution")
        self.assertEqual(rows[1]["arms"]["p9_no_probe"]["reference_cache"]["kind"],
                         "identical_prompt1_execution")


if __name__ == "__main__":
    unittest.main()

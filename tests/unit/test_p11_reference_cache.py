from __future__ import annotations

import copy
import unittest

from scripts.p11_reference_cache import reuse_known_best_result, reuse_prompt1_result
from starnet.experiments.seeds import seed_payload


def with_prompts(seed, values):
    result = copy.deepcopy(seed)
    result["prompts"] = {str(index): value for index, value in enumerate(values, 1)}
    return result


class P11ReferenceCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = seed_payload("er_balanced", 50, 1)

    def test_prompt1_reuse_accepts_only_same_consumed_state_and_strength(self) -> None:
        source = with_prompts(self.base, (15.0, 10.0, -5.0))
        target = with_prompts(self.base, (15.0, -5.0, 10.0))
        result = {"action_log": [{"kind": "comm", "prompt_id": 1}],
                  "action_log_sha256": "source"}
        reused = reuse_prompt1_result(result, source, target, source_case_id="consumed")
        self.assertEqual(reused["reference_cache"]["kind"], "identical_prompt1_execution")
        with self.assertRaises(ValueError):
            reuse_prompt1_result(result, source, with_prompts(self.base, (10.0, 15.0, -5.0)),
                                 source_case_id="consumed")

    def test_known_best_relabels_ids_but_preserves_public_result(self) -> None:
        source = with_prompts(self.base, (15.0, 10.0, -5.0))
        target = with_prompts(self.base, (10.0, 15.0, -5.0))
        result = {"action_log": [{"kind": "comm", "prompt_id": 1,
                                  "requested_prompt_id": 1, "dispatched_prompt_id": 1,
                                  "public_result": {"status": "success", "new_w": 4.0}}],
                  "action_log_sha256": "source", "known_prompt_id": 1}
        reused = reuse_known_best_result(
            result, source, target, source_prompt_id=1, target_prompt_id=2,
            source_case_id="consumed",
        )
        self.assertEqual(reused["action_log"][0]["prompt_id"], 2)
        self.assertEqual(reused["action_log"][0]["dispatched_prompt_id"], 2)
        self.assertEqual(reused["action_log"][0]["public_result"],
                         result["action_log"][0]["public_result"])
        self.assertNotEqual(reused["action_log_sha256"], "source")

    def test_reuse_rejects_different_graph_state_or_wrong_trace(self) -> None:
        source = with_prompts(self.base, (15.0, 10.0, -5.0))
        other = seed_payload("ba_negative_hubs", 50, 1)
        with self.assertRaises(ValueError):
            reuse_prompt1_result({"action_log": [], "action_log_sha256": "x"},
                                 source, other, source_case_id="x")
        with self.assertRaises(ValueError):
            reuse_prompt1_result({"action_log": [{"kind": "comm", "prompt_id": 2}],
                                  "action_log_sha256": "x"}, source, source,
                                 source_case_id="x")


if __name__ == "__main__":
    unittest.main()

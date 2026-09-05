"""The performance gate must reject incomplete, unpaired or unsafe V1 runs."""

from __future__ import annotations

import unittest

from scripts.promote_v1 import decision


def row(seed: str, repetition: int, variant: str, score: float) -> dict[str, object]:
    return {
        "phase": "main", "plan_hash": "plan", "matrix_branch": "stable", "seed_id": seed,
        "repetition": repetition, "variant": variant, "final_score": score,
        "comparable": True, "protocol_error": None, "action_failures": 0,
        "llm_calls": 0,
    }


class V1PromotionTests(unittest.TestCase):
    def test_requires_all_six_seeds_and_three_paired_repetitions(self) -> None:
        rows = [row("seed-1", 1, "v0_deterministic", 1.0), row("seed-1", 1, "v1_cmg", 2.0)]
        outcome = decision({"gate_passed": True}, rows)
        self.assertFalse(outcome["promoted"])

    def test_rejects_any_llm_use(self) -> None:
        rows = [
            item
            for seed in range(6)
            for repetition in range(1, 4)
            for item in (row(str(seed), repetition, "v0_deterministic", 1.0), row(str(seed), repetition, "v1_cmg", 2.0))
        ]
        rows[-1]["llm_calls"] = 1
        outcome = decision({"gate_passed": True}, rows)
        self.assertFalse(outcome["promoted"])
        self.assertTrue(any("LLM" in issue for issue in outcome["issues"]))

    def test_rejects_missing_cohort_metadata(self) -> None:
        rows = [row("seed-1", 1, "v0_deterministic", 1.0), row("seed-1", 1, "v1_cmg", 2.0)]
        for item in rows:
            item["plan_hash"] = None
            item["matrix_branch"] = None
        outcome = decision({"gate_passed": True}, rows)
        self.assertFalse(outcome["promoted"])
        self.assertTrue(any("invalid" in issue for issue in outcome["issues"]))


if __name__ == "__main__":
    unittest.main()

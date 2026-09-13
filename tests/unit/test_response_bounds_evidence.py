"""Recompute the public response-bound evidence from recorded API returns."""

from pathlib import Path
import json
import unittest

from starnet.policy.cmg import bounded_response_delta


class ResponseBoundsEvidenceTests(unittest.TestCase):
    def test_all_public_probe_updates_match_the_policy_helper(self) -> None:
        root = Path(__file__).resolve().parents[2]
        report = json.loads(
            (root / "experiments/reports/p9-response-bounds-probe-20260913.json")
            .read_text(encoding="utf-8")
        )
        strengths = {1: 15.0, 3: -5.0}
        checked = 0
        clipped = 0
        for run in report["runs"]:
            factor = float(run["factor"])
            strength = strengths[run["prompt_id"]]
            for item in run["observations"]:
                self.assertEqual(float(item["scanned_w"]), float(item["initial_w"]))
                nominal = strength * factor * 0.5 ** (int(item["turn"]) - 1)
                previous = float(item["previous_w"])
                expected = previous + bounded_response_delta(previous, nominal)
                observed = float(item["response"]["new_w"])
                self.assertEqual(observed, expected)
                self.assertEqual(observed, float(item["bounded_prediction"]))
                checked += 1
                clipped += int(observed != previous + nominal)
        self.assertEqual(checked, 108)
        self.assertGreater(clipped, 0)


if __name__ == "__main__":
    unittest.main()

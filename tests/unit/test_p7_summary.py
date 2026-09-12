"""Incomplete matrices and resource violations must not yield a P7 gain."""

import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_robust_search import BLOCKS
from scripts.summarize_p7_search import summarize


class SummaryTests(unittest.TestCase):
    def report(self):
        baseline = {"score": 1.0, "failures": 0, "remaining_budget": 75.0,
                    "actions": {"scan": 50, "comm": 0, "cut": 0, "shield": 0}}
        return {"config": {"nodes": 50}, "rows": [
            {"family": family, "repetition": 301, "variant": "test",
             "baseline": baseline.copy(), "candidate": {**baseline, "score": 2.0}, "delta": 1.0}
            for families, _ in BLOCKS.values() for family in families]}

    def evaluate(self, report):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            return summarize([path], [301])

    def test_complete_paired_cohort(self):
        result = self.evaluate(self.report())["summary"]["test"]
        self.assertEqual(result["cases"], 13)
        self.assertEqual(result["mean_delta"], 1.0)
        self.assertTrue(result["statistical_gate_passed"])

    def test_missing_and_duplicate_case_rejected(self):
        report = self.report()
        report["rows"].pop()
        with self.assertRaises(ValueError):
            self.evaluate(report)
        report = self.report()
        report["rows"].append(report["rows"][0])
        with self.assertRaises(ValueError):
            self.evaluate(report)

    def test_score_and_budget_tampering_rejected(self):
        for field, value in (("remaining_budget", 100), ("score", float("nan")), ("failures", 1), ("steps", 1)):
            report = self.report()
            report["rows"][0]["candidate"][field] = value
            with self.assertRaises(ValueError):
                self.evaluate(report)


if __name__ == "__main__":
    unittest.main()

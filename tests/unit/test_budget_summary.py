from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.summarize_budget_search import summarize


class BudgetSummaryTests(unittest.TestCase):
    def test_rejects_duplicate_and_incomplete_confirmation(self):
        data = {"config": {"depth": 2, "width": 4, "start": 101, "repetitions": 5, "nodes": 50},
                "rows": [{"family": "er_balanced", "repetition": 101}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incomplete"):
                summarize([path])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                summarize([path, path])

    def test_development_results_cannot_be_relabelled_as_confirmation(self):
        data = {"config": {"depth": 2, "width": 4, "start": 31, "repetitions": 3, "nodes": 50}, "rows": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "101 through 105"):
                summarize([path])


if __name__ == "__main__":
    unittest.main()

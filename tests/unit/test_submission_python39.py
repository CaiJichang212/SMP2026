"""Regression checks for the official Python 3.9 submission runtime."""

from pathlib import Path
import ast
import unittest

from scripts.validate_submission import PY39_MISSING_TYPING_NAMES, unsupported_python39_typing_names


class SubmissionPython39Tests(unittest.TestCase):
    def test_type_alias_is_not_required_by_submission_sources(self):
        root = Path(__file__).resolve().parents[2]
        runtime_sources = [root / "src/starnet/policy/fast_settlement_experiment.py"]
        for path in runtime_sources:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("from typing import TypeAlias", source)
            self.assertNotIn(": TypeAlias =", source)

    def test_validator_tracks_typing_names_missing_from_python39(self):
        self.assertIn("TypeAlias", PY39_MISSING_TYPING_NAMES)
        self.assertIn("Self", PY39_MISSING_TYPING_NAMES)
        tree = ast.parse("from typing import Any, TypeAlias, Self\n")
        self.assertEqual(unsupported_python39_typing_names(tree), ["Self", "TypeAlias"])


if __name__ == "__main__":
    unittest.main()

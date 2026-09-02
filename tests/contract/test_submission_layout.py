import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUBMISSION_DIR = PROJECT_ROOT / "SMP_Starter_Kit" / "team_submission"


class SubmissionLayoutTests(unittest.TestCase):
    def test_submission_has_only_contract_top_level_entries(self) -> None:
        self.assertEqual(
            {path.name for path in SUBMISSION_DIR.iterdir()},
            {"config.json", "prompt", "starnet_model.py"},
        )

    def test_submission_model_is_parseable_and_exports_required_class(self) -> None:
        source = (SUBMISSION_DIR / "starnet_model.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
        self.assertIn("ParticipantSquadModel", class_names)


if __name__ == "__main__":
    unittest.main()

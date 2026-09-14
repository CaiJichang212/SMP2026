"""Static checks for the temporary P11 single-file entry."""

import ast
import unittest

from scripts.check_p11_research_entry import EXPERIMENT_MODULES, assemble_p11_entry


class P11ResearchEntryTests(unittest.TestCase):
    def test_python39_entry_has_no_project_import_or_collision(self):
        source, audit = assemble_p11_entry()
        ast.parse(source, feature_version=(3, 9))
        self.assertTrue(audit["python39_ast_passed"])
        self.assertEqual(audit["top_level_collisions"], [])
        self.assertEqual(audit["residual_starnet_imports"], [])
        self.assertIn("PromptLearningRuntimeController", source)
        self.assertIn("P11_CERTIFIED_MODE", source)

    def test_only_prompt_learning_modules_are_added(self):
        self.assertEqual(EXPERIMENT_MODULES, (
            "src/starnet/policy/prompt_calibration_experiment.py",
            "src/starnet/runtime/p11_prompt_controller_experiment.py",
        ))


if __name__ == "__main__":
    unittest.main()

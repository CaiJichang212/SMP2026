"""Static isolation checks for the temporary P10 research entry."""

import ast
import unittest

from scripts.check_p10_research_entry import (
    EXPERIMENT_MODULES,
    VARIANTS,
    assemble_research_entry,
)


class P10ResearchEntryTests(unittest.TestCase):
    def test_every_variant_is_python39_single_file_without_project_imports(self):
        hashes = set()
        for variant in VARIANTS:
            source, audit = assemble_research_entry(variant)
            ast.parse(source, feature_version=(3, 9))
            self.assertEqual(audit["top_level_collisions"], [])
            self.assertEqual(audit["residual_starnet_imports"], [])
            self.assertTrue(audit["python39_ast_passed"])
            self.assertIn(f"experiment_mode='{variant}'", source)
            hashes.add(hash(source))
        self.assertEqual(len(hashes), len(VARIANTS))

    def test_exact_experiment_modules_are_added(self):
        self.assertEqual(EXPERIMENT_MODULES, (
            "src/starnet/policy/public_response_mixture.py",
            "src/starnet/policy/p9_prefix_experiment.py",
            "src/starnet/policy/p10_structure_plan_experiment.py",
            "src/starnet/runtime/p10_controller_experiment.py",
        ))

    def test_unknown_variant_fails_before_assembly(self):
        with self.assertRaises(ValueError):
            assemble_research_entry("unknown")


if __name__ == "__main__":
    unittest.main()

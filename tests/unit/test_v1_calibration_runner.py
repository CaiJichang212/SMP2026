"""Pre-registered calibration collection plan tests; no network access."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.run_v1_calibration import response_specs, settlement_specs, stable_plan


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class V1CalibrationRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(
            (PROJECT_ROOT / "experiments" / "manifests" / "v1-calibration.json").read_text(encoding="utf-8")
        )

    def test_preregistered_session_counts_are_complete(self) -> None:
        self.assertEqual(len(response_specs(self.manifest)), 135)
        self.assertEqual(len(settlement_specs(self.manifest)), 420)
        self.assertEqual(len(stable_plan(self.manifest, "all")), 555)

    def test_every_settlement_cell_has_a_legal_declared_target(self) -> None:
        for spec in settlement_specs(self.manifest):
            seed = spec["seed"]
            node_ids = {node["id"] for node in seed["nodes"]}
            edges = {tuple(sorted(edge)) for edge in seed["edges"]}
            action = spec["action"]
            kind = action["kind"]
            if kind == "control":
                continue
            self.assertIn(action["target_node_1"], node_ids)
            if kind == "cut":
                self.assertIn(
                    tuple(sorted((action["target_node_1"], action["target_node_2"]))), edges
                )


if __name__ == "__main__":
    unittest.main()

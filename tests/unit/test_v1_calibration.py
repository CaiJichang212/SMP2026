"""Offline V1 calibration report guardrails."""

from __future__ import annotations

import unittest

from scripts.calibrate_v1 import build_report, required_response_keys, score_for_row
from starnet.policy.calibration import CalibrationProfile


SNAPSHOT = {
    "nodes": {"1": {"w": 1.0, "persona": "和平", "comm_left": 3}},
    "edges": [],
    "dead_nodes": [],
}


class V1CalibrationTests(unittest.TestCase):
    def test_control_scores_unchanged_state(self) -> None:
        row = {"before_snapshot": SNAPSHOT, "action": {"kind": "control"}}
        self.assertEqual(score_for_row(row, CalibrationProfile(False)), 1.0)

    def test_missing_response_table_keeps_embedded_winner_unverified(self) -> None:
        rows = [
            {
                "kind": "settlement", "split": split, "graph_id": split,
                "terminal_hash": split, "before_snapshot": SNAPSHOT,
                "action": {"kind": "control"}, "final_score": 1.0,
            }
            for split in ("calibration", "selection", "gate")
        ]
        manifest = {"response_protocol": {"personas": ["和平"], "prompt_ids": [1], "communications_per_session": 1}}
        report = build_report(manifest, rows)
        self.assertFalse(report["gate_passed"])
        self.assertFalse(report["winner"]["gate_passed"])
        self.assertFalse(report["gate"]["response_prior_coverage"])

    def test_required_response_keys_cover_every_preregistered_turn(self) -> None:
        manifest = {"response_protocol": {"personas": ["和平", "中立"], "prompt_ids": [1, 2], "communications_per_session": 3}}
        self.assertEqual(len(required_response_keys(manifest)), 12)

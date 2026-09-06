"""Offline V1 calibration report guardrails."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.calibrate_v1 import board_from_snapshot, build_report, mae, required_response_keys, score_for_row, settlement_coverage, topology_holdout
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.cmg import CMGPlanningError, PredictiveState, SettlementPredictor


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

    def test_nonconvergent_predictor_is_scored_as_infinite_error(self) -> None:
        # A divergent grid candidate must be rejected rather than aborting
        # the complete calibration analysis.
        row = {"before_snapshot": SNAPSHOT, "action": {"kind": "control"}, "final_score": 1.0}
        with patch("scripts.calibrate_v1.score_for_row", side_effect=CMGPlanningError("nonconvergent")):
            self.assertEqual(mae([row], CalibrationProfile(False)), float("inf"))

    def test_component_degree_plus_one_preserves_each_component_score(self) -> None:
        board = board_from_snapshot({
            "nodes": {
                "1": {"w": -42.0, "persona": "暴力", "comm_left": 3},
                "2": {"w": 12.0, "persona": "和平", "comm_left": 3},
                "3": {"w": -14.0, "persona": "中立", "comm_left": 3},
            },
            "edges": [[1, 2]],
            "dead_nodes": [],
        })
        profile = CalibrationProfile(False, model="component_degree_plus_one")
        self.assertAlmostEqual(SettlementPredictor(profile).score(PredictiveState.from_blackboard(board)), -44.0)

    def test_topology_holdout_rejects_reused_families(self) -> None:
        repeated = [{"graph_id": "path5-positive"}]
        disjoint = {
            "calibration": repeated,
            "selection": [{"graph_id": "triangle-mixed"}],
            "gate": [{"graph_id": "star5-negative"}],
        }
        self.assertFalse(topology_holdout({key: repeated for key in disjoint}))
        self.assertTrue(topology_holdout(disjoint))

    def test_settlement_coverage_rejects_undeclared_graph_replacement(self) -> None:
        manifest = {
            "settlement_protocol": {
                "graph_families": {"calibration": ["path4"], "selection": ["star4"], "gate": ["triangle4"]},
                "layouts_by_split": {split: ["mixed"] for split in ("calibration", "selection", "gate")},
                "splits": ["calibration", "selection", "gate"], "actions": ["control"], "repetitions": 1,
            }
        }
        rows = [
            {"split": "calibration", "graph_id": "path4-mixed", "action": {"kind": "control"}, "comparable": True},
            {"split": "selection", "graph_id": "star4-mixed", "action": {"kind": "control"}, "comparable": True},
            # Same count as the expected gate set, but not its declared graph.
            {"split": "gate", "graph_id": "substitute-mixed", "action": {"kind": "control"}, "comparable": True},
        ]
        self.assertFalse(settlement_coverage(rows, manifest))

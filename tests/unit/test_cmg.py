"""V1 CMG is pure, deterministic and fail-closed."""

from __future__ import annotations

from dataclasses import asdict
import unittest

from starnet.model.blackboard import Blackboard
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.cmg import ResponseLedger, SettlementPredictor, PredictiveState, choose_cmg_action, enumerate_cmg_actions


def profile() -> CalibrationProfile:
    draft = CalibrationProfile(
        gate_passed=True,
        model="degree",
        settlement_residual_std={"comm": 0.0, "cut": 0.0, "shield": 0.0},
        response_mean={"和平|1|1": 5.0},
        response_std={"和平|1|1": 0.0},
        manifest_hash="manifest",
        data_hash="data",
    )
    return CalibrationProfile(**{**asdict(draft), "profile_hash": draft.computed_hash()})


class CMGTests(unittest.TestCase):
    def board(self) -> Blackboard:
        board = Blackboard()
        board.record_scan(1, {"w": 1.0, "persona": "和平", "comm_left": 3, "neighbors": []})
        return board

    def test_degree_predictor_and_hypothesis_do_not_mutate_blackboard(self) -> None:
        board = self.board()
        state = PredictiveState.from_blackboard(board)
        self.assertEqual(SettlementPredictor(profile()).score(state), 1.0)
        after = state.apply(enumerate_cmg_actions(board, 10.0, 64)[0], 5.0)
        self.assertEqual(SettlementPredictor(profile()).score(after), 6.0)
        self.assertEqual(board.nodes[1].w, 1.0)
        self.assertEqual(board.nodes[1].comm_left, 3)

    def test_response_ledger_uses_first_observation_then_decay(self) -> None:
        ledger = ResponseLedger()
        active = profile()
        self.assertEqual(ledger.predicted_delta(1, "和平", 1, active), (5.0, 0.0))
        ledger.record_success(1, 1.0, 9.0)
        self.assertEqual(ledger.successful_comm_count[1], 1)
        self.assertEqual(ledger.predicted_delta(1, "和平", 1, active), (4.0, 0.0))
        ledger.record_success(1, 9.0, 13.0)
        self.assertEqual(ledger.predicted_delta(1, "和平", 1, active), (2.0, 0.0))

    def test_positive_lcb_and_lexical_tie_break(self) -> None:
        board = self.board()
        selected = choose_cmg_action(board, ResponseLedger(), profile(), 10.0)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.candidate_id, "comm:1:1")
        self.assertGreater(selected.lcb_roi, 0.0)

    def test_dense_cut_filter_has_exact_stable_limit(self) -> None:
        board = Blackboard()
        for node_id in range(1, 13):
            board.record_scan(node_id, {"w": -float(node_id), "persona": "暴力", "comm_left": 0, "neighbors": [other for other in range(1, 13) if other != node_id]})
        cuts = [action for action in enumerate_cmg_actions(board, 1_000.0, 64) if action.kind == "cut"]
        self.assertEqual(len(cuts), 64)
        self.assertEqual(cuts, enumerate_cmg_actions(board, 1_000.0, 64)[-64:])

    def test_response_standard_deviation_is_transformed_to_score_units(self) -> None:
        board = Blackboard()
        # Node 1 has degree ten, so a ±2 w response error is ±20 score units.
        board.record_scan(1, {"w": 0.0, "persona": "和平", "comm_left": 3, "neighbors": list(range(2, 12))})
        for node_id in range(2, 12):
            board.record_scan(node_id, {"w": 0.0, "persona": "暴力", "comm_left": 0, "neighbors": [1]})
        draft = CalibrationProfile(
            gate_passed=True,
            settlement_residual_std={"comm": 0.0, "cut": 0.0, "shield": 0.0},
            response_mean={"和平|1|1": 1.0},
            response_std={"和平|1|1": 2.0},
            manifest_hash="manifest",
            data_hash="data",
        )
        uncertain = CalibrationProfile(**{**asdict(draft), "profile_hash": draft.computed_hash()})
        self.assertIsNone(choose_cmg_action(board, ResponseLedger(), uncertain, 100.0))


if __name__ == "__main__":
    unittest.main()

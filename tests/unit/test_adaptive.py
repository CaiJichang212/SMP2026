"""B5 scenario consistency, same-scenario VOI and scout determinism."""

from __future__ import annotations

import unittest

from starnet.model.blackboard import Blackboard
from starnet.model.blackboard import NodeState
from starnet.policy.adaptive import AdaptiveScout, Scenario, ScenarioProfile, evaluate_scan_voi
from starnet.policy.cmg import PredictiveState


def scanned_board() -> Blackboard:
    board = Blackboard(node_count=4)
    board.record_scan(1, {"w": 1.0, "persona": "和平", "comm_left": 3, "neighbors": [2]})
    return board


class AdaptiveTests(unittest.TestCase):
    def test_invalid_scenario_profile_is_not_usable(self) -> None:
        profile = ScenarioProfile()
        self.assertFalse(profile.verified)
        self.assertFalse(profile.is_consistent(scanned_board()))

    def test_scenarios_cannot_add_edge_for_a_scanned_node(self) -> None:
        board = scanned_board()
        state = PredictiveState.from_blackboard(board)
        bad = PredictiveState(dict(state.nodes), {(1, 3)}, set())
        profile = ScenarioProfile((Scenario("bad", bad, {}, 1.0),), True, True)
        self.assertFalse(profile.is_consistent(board))

    def test_voi_uses_the_same_scenario_before_and_after(self) -> None:
        board = Blackboard(node_count=2)
        # The scenario is complete (w=5), but that value may only enter after
        # the branch's scan observation.  It must not leak into the common
        # pre-scan value.
        state = PredictiveState({1: NodeState(5.0, "和平", 3)}, set(), set())
        observation = {"w": 5.0, "persona": "和平", "comm_left": 3, "neighbors": []}
        profile = ScenarioProfile((Scenario("s", state, {1: observation}, 1.0),), True, True)
        value = evaluate_scan_voi(board, 1, profile, lambda candidate: sum(item.w for item in candidate.nodes.values()))
        self.assertEqual(value.voi, 4.5)
        self.assertEqual(value.evidence_ids, ("scenario:s:scan:1",))

    def test_voi_can_use_replanned_branch_value_with_reduced_resources(self) -> None:
        board = Blackboard(node_count=2)
        state = PredictiveState({1: NodeState(2.0, "和平", 3)}, set(), set())
        profile = ScenarioProfile((Scenario("s", state, {}, 1.0),), True, True)
        value = evaluate_scan_voi(
            board,
            1,
            profile,
            lambda _state: 1.0,
            branch_value_fn=lambda _state: 4.0,
            scan_cost=0.0,
        )
        self.assertEqual(value.voi, 3.0)

    def test_scenarios_with_a_publicly_dead_node_are_rejected(self) -> None:
        board = Blackboard(node_count=2)
        board.record_scan(1, {"w": 1.0, "persona": "和平", "comm_left": 3, "neighbors": []})
        board.record_shield(1, True)
        invalid_state = PredictiveState({1: NodeState(1.0, "和平", 3)}, set(), set())
        profile = ScenarioProfile((Scenario("dead", invalid_state, {}, 1.0),), True, True)
        self.assertFalse(profile.is_consistent(board))

    def test_adaptive_initial_sample_is_fixed_and_then_keeps_frontier_and_blind(self) -> None:
        first = AdaptiveScout(10, initial_count=4, seed=7)
        second = AdaptiveScout(10, initial_count=4, seed=7)
        board1 = Blackboard(node_count=10)
        board2 = Blackboard(node_count=10)
        first_ids = [first.next_action(board1).target_node_1 for _ in range(4)]  # type: ignore[union-attr]
        second_ids = [second.next_action(board2).target_node_1 for _ in range(4)]  # type: ignore[union-attr]
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(len(set(first_ids)), 4)
        board1.record_scan(first_ids[0], {"w": 0.0, "persona": "中立", "comm_left": 3, "neighbors": [10]})
        next_id = first.next_action(board1).target_node_1  # type: ignore[union-attr]
        self.assertEqual(next_id, 10)

    def test_unseen_response_uses_observed_group_posterior(self) -> None:
        from starnet.policy.calibration import CalibrationProfile
        from starnet.policy.cmg import ResponseLedger

        profile = CalibrationProfile(
            gate_passed=True,
            response_mean={"和平|1|1": 1.0},
            response_std={"和平|1|1": 1.0},
            manifest_hash="m",
            data_hash="d",
        )
        draft = profile
        profile = CalibrationProfile(**{**draft.__dict__, "profile_hash": draft.computed_hash()})
        ledger = ResponseLedger()
        ledger.record_success(9, 0.0, 4.0, persona="和平", prompt_id=1, turn=1)
        prediction = ledger.predicted_delta(10, "和平", 1, profile)
        self.assertEqual(prediction, (4.0, 0.0))


if __name__ == "__main__":
    unittest.main()

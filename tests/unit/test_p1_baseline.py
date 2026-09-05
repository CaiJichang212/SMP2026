"""P1 guardrails: all scans first, no structure actions, bounded completion."""

from __future__ import annotations

import unittest

from starnet.policy.config import DEFAULT_POLICY_CONFIG
from starnet.policy.baseline import persuasion_candidates
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.model.blackboard import Blackboard
from starnet.runtime.controller import RuntimeController
from starnet.runtime.stage import ContestStage


class PathEnvironment:
    def __init__(self, count: int, budget: float) -> None:
        self.budget = budget
        self.count = count
        self.comm_left = {node_id: 3 for node_id in range(1, count + 1)}
        self.w = {node_id: 0.0 for node_id in range(1, count + 1)}
        self.calls: list[tuple[object, ...]] = []

    def get_remaining_budget(self) -> float:
        return self.budget

    def scan_node(self, node_id: int) -> dict[str, object] | None:
        self.calls.append(("scan", node_id))
        self.budget -= 0.5
        return {
            "w": self.w[node_id], "persona": "和平", "comm_left": self.comm_left[node_id],
            "neighbors": [item for item in (node_id - 1, node_id + 1) if 1 <= item <= self.count],
        }

    def communicate(self, node_id: int, prompt_id: int) -> dict[str, object]:
        self.calls.append(("comm", node_id, prompt_id))
        self.budget -= 2.0
        self.comm_left[node_id] -= 1
        self.w[node_id] += 1.0
        return {"status": "success", "new_w": self.w[node_id], "comm_left": self.comm_left[node_id]}

    def cut_link(self, left: int, right: int) -> bool:
        self.calls.append(("cut", left, right))
        return False

    def shield_node(self, node_id: int) -> bool:
        self.calls.append(("shield", node_id))
        return False


class P1BaselineTests(unittest.TestCase):
    def test_explicit_stages_and_safe_caps(self) -> None:
        preliminary = RuntimeController(PathEnvironment(50, 100.0), config=DEFAULT_POLICY_CONFIG)
        final = RuntimeController(PathEnvironment(100, 200.0), config=DEFAULT_POLICY_CONFIG, stage=ContestStage.FINAL)
        self.assertEqual((preliminary.stage.node_count, preliminary._safe_step_limit), (50, 117))
        self.assertEqual((final.stage.node_count, final._safe_step_limit), (100, 247))

    def test_explicit_100_node_override_uses_final_cap_without_budget_inference(self) -> None:
        controller = RuntimeController(PathEnvironment(100, 100.0), node_count=100, config=DEFAULT_POLICY_CONFIG)
        self.assertEqual((controller.stage.node_count, controller._safe_step_limit), (100, 247))

    def test_first_observed_response_is_diminished_for_later_slots(self) -> None:
        board = Blackboard(node_count=2)
        board.record_scan(1, {"w": 0.0, "persona": "和平", "comm_left": 3, "neighbors": [2]})
        board.record_scan(2, {"w": 0.0, "persona": "和平", "comm_left": 3, "neighbors": [1]})
        first = persuasion_candidates(board, 10.0, {1: 8.0}, DEFAULT_CALIBRATION_PROFILE)
        self.assertEqual(next(item for item in first if item.candidate_id == "comm:1:1").score, 8.0)
        board.record_communication(1, {"status": "success", "new_w": 8.0, "comm_left": 2})
        second = persuasion_candidates(board, 10.0, {1: 8.0}, DEFAULT_CALIBRATION_PROFILE)
        self.assertEqual(next(item for item in second if item.candidate_id == "comm:1:2").score, 4.0)

    def test_failed_b1_slot_is_not_regenerated(self) -> None:
        env = PathEnvironment(2, 20.0)

        def reject(node_id: int, prompt_id: int) -> dict[str, object]:
            env.calls.append(("comm", node_id, prompt_id))
            return {"status": "temporarily_rejected"}

        env.communicate = reject  # type: ignore[method-assign]
        controller = RuntimeController(env, node_count=2, config=DEFAULT_POLICY_CONFIG)
        while not controller.stopped:
            controller.step()
        comm_nodes = [call[1] for call in env.calls if call[0] == "comm"]
        self.assertEqual(sorted(comm_nodes), [1, 2])

    def test_full_preliminary_run_scans_before_b1_and_stays_within_limits(self) -> None:
        env = PathEnvironment(50, 100.0)
        controller = RuntimeController(env, config=DEFAULT_POLICY_CONFIG)
        while not controller.stopped:
            controller.step()
        scan_positions = [index for index, call in enumerate(env.calls) if call[0] == "scan"]
        comm_positions = [index for index, call in enumerate(env.calls) if call[0] == "comm"]
        self.assertEqual(len(scan_positions), 50)
        self.assertEqual(scan_positions, list(range(50)))
        self.assertTrue(comm_positions)
        self.assertLessEqual(len(env.calls), 87)
        self.assertLessEqual(controller.step_number, 117)
        self.assertEqual(controller.llm_calls, 0)
        self.assertFalse(any(call[0] in {"cut", "shield"} for call in env.calls))

    def test_unknown_comm_left_causes_stop_without_communication(self) -> None:
        env = PathEnvironment(1, 10.0)
        original = env.scan_node

        def scan_unknown(node_id: int) -> dict[str, object] | None:
            result = original(node_id)
            assert result is not None
            result.pop("comm_left")
            return result

        env.scan_node = scan_unknown  # type: ignore[method-assign]
        controller = RuntimeController(env, node_count=1, config=DEFAULT_POLICY_CONFIG)
        while not controller.stopped:
            controller.step()
        self.assertEqual([call[0] for call in env.calls], ["scan"])


if __name__ == "__main__":
    unittest.main()

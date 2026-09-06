"""Configuration switches must be observable without changing V0 defaults."""

from __future__ import annotations

import unittest

from starnet.policy.config import DEFAULT_POLICY_CONFIG, PolicyConfig
from starnet.policy.actions import Action
from starnet.policy.candidates import Candidate
from starnet.policy.config import PolicyMode
from starnet.policy.graph_analysis import analyze_graph
from starnet.runtime.controller import RuntimeController, StopReason
from starnet.runtime.stage import ContestStage


class TinyEnvironment:
    def __init__(self) -> None:
        self.budget = 10.0
        self.calls: list[tuple[object, ...]] = []

    def get_remaining_budget(self) -> float:
        return self.budget

    def scan_node(self, node_id: int) -> dict[str, object] | None:
        self.calls.append(("scan", node_id))
        self.budget -= 0.5
        return {"w": 1.0, "persona": "和平", "comm_left": 3, "neighbors": []}

    def communicate(self, node_id: int, prompt_id: int) -> dict[str, object]:
        self.calls.append(("comm", node_id, prompt_id))
        self.budget -= 2.0
        return {"status": "success", "new_w": 2.0}

    def cut_link(self, left: int, right: int) -> bool:
        self.calls.append(("cut", left, right))
        return False

    def shield_node(self, node_id: int) -> bool:
        self.calls.append(("shield", node_id))
        return False


class PolicyConfigTests(unittest.TestCase):
    def test_default_is_immutable_conservative_b1_configuration(self) -> None:
        self.assertTrue(DEFAULT_POLICY_CONFIG.p0_exclusive)
        self.assertEqual(DEFAULT_POLICY_CONFIG.max_llm_calls, 0)
        self.assertFalse(DEFAULT_POLICY_CONFIG.enable_shield)
        self.assertFalse(DEFAULT_POLICY_CONFIG.enable_cut)
        self.assertEqual(DEFAULT_POLICY_CONFIG.safety_step_limit(50), 117)
        self.assertEqual(DEFAULT_POLICY_CONFIG.safety_step_limit(100), 247)
        with self.assertRaises(Exception):
            DEFAULT_POLICY_CONFIG.max_llm_calls = 0  # type: ignore[misc]

    def test_scan_only_stops_after_final_scan(self) -> None:
        environment = TinyEnvironment()
        controller = RuntimeController(
            environment, node_count=1, config=PolicyConfig(max_llm_calls=0, stop_after_scan=True)
        )
        self.assertEqual(controller.step(), 0)
        self.assertTrue(controller.stopped)
        self.assertEqual(controller.stop_reason, StopReason.NO_CANDIDATES)
        self.assertEqual(environment.calls, [("scan", 1)])

    def test_step_fuse_reserves_headroom_and_llm_config_cannot_exceed_public_cap(self) -> None:
        environment = TinyEnvironment()
        controller = RuntimeController(environment, node_count=1, config=PolicyConfig(max_steps=2))
        self.assertEqual(controller.step(), 0)
        self.assertEqual(controller.step(), 1)
        self.assertEqual(controller.step_number, 2)
        self.assertEqual(controller.stop_reason, StopReason.STEP_LIMIT)
        final_controller = RuntimeController(
            TinyEnvironment(), lambda _: {}, node_count=100, stage=ContestStage.FINAL,
            config=PolicyConfig(max_llm_calls=999)
        )
        self.assertEqual(final_controller.commander.max_llm_calls, 250)

    def test_invalid_limits_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PolicyConfig(max_llm_calls=-1)
        with self.assertRaises(ValueError):
            PolicyConfig(max_steps=0)

    def test_structural_plan_selection_never_builds_a_batch(self) -> None:
        environment = TinyEnvironment()
        controller = RuntimeController(
            environment,
            node_count=2,
            config=PolicyConfig(policy_mode=PolicyMode.B3_SINGLE_STRUCTURE, max_llm_calls=0),
        )
        controller.blackboard.record_scan(1, {"w": 1.0, "persona": "和平", "comm_left": 3, "neighbors": []})
        controller.blackboard.record_scan(2, {"w": 1.0, "persona": "和平", "comm_left": 3, "neighbors": []})
        controller.analysis = analyze_graph(controller.blackboard)
        controller.effective_policy_mode = PolicyMode.B3_SINGLE_STRUCTURE
        first = Candidate("plan:first", Action("comm", 1, prompt_id=1), 0, 2.0, 2.0, "first")
        second = Candidate("plan:second", Action("comm", 2, prompt_id=1), 0, 1.0, 1.0, "second")
        controller.candidates = {first.candidate_id: first, second.candidate_id: second}

        controller._create_plan(10.0)

        self.assertEqual(controller.queue, ["plan:first"])

    def test_failed_first_action_suppresses_every_shared_plan(self) -> None:
        environment = TinyEnvironment()
        controller = RuntimeController(environment, node_count=1)
        controller.blackboard.record_scan(1, {"w": 1.0, "persona": "和平", "comm_left": 3, "neighbors": []})
        action = Action("comm", 1, prompt_id=1)
        controller.candidates = {
            "plan:left": Candidate("plan:left", action, 0, 1.0, 1.0, "left"),
            "plan:right": Candidate("plan:right", action, 0, 1.0, 1.0, "right"),
        }
        controller.failed_actions.add(action)

        validation = controller._valid_queue(["plan:left", "plan:right"], 10.0)

        self.assertEqual(validation.candidate_ids, ())
        self.assertEqual([item["reason"] for item in validation.discarded], ["failed_action", "failed_action"])


if __name__ == "__main__":
    unittest.main()

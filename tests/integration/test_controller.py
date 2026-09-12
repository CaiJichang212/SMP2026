"""运行时状态机的模拟环境集成测试。"""

from __future__ import annotations

import unittest
import ast
import json
import re
from dataclasses import asdict

from starnet.runtime.controller import ControllerState, RuntimeController, StopReason
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.config import PolicyConfig, PolicyMode
from starnet.policy.actions import Action
from starnet.runtime.stage import ContestStage
from starnet.submission.starnet_model import ParticipantSquadModel


class FakeStarNetEnvironment:
    """只模拟赛题公开 API，并记录控制器实际请求的动作。"""

    def __init__(self, node_count: int, budget: float, *, reject_communication: bool = False) -> None:
        self.budget = budget
        self.reject_communication = reject_communication
        self.calls: list[tuple[object, ...]] = []
        self.nodes = {
            node_id: {
                "w": 2.0,
                "persona": "和平",
                "comm_left": 3,
                "neighbors": self._neighbors(node_id, node_count),
            }
            for node_id in range(1, node_count + 1)
        }
        self.edges = {
            (node_id, node_id + 1)
            for node_id in range(1, node_count)
        }

    @staticmethod
    def _neighbors(node_id: int, node_count: int) -> list[int]:
        neighbors: list[int] = []
        if node_id > 1:
            neighbors.append(node_id - 1)
        if node_id < node_count:
            neighbors.append(node_id + 1)
        return neighbors

    def get_remaining_budget(self) -> float:
        return self.budget

    def scan_node(self, node_id: int) -> dict[str, object] | None:
        self.calls.append(("scan", node_id))
        if self.budget < 0.5 or node_id not in self.nodes:
            return None
        self.budget -= 0.5
        node = self.nodes[node_id]
        return {
            "w": node["w"],
            "persona": node["persona"],
            "comm_left": node["comm_left"],
            "neighbors": list(node["neighbors"]),
        }

    def communicate(self, node_id: int, prompt_id: int) -> dict[str, object]:
        self.calls.append(("comm", node_id, prompt_id))
        node = self.nodes[node_id]
        if self.budget < 2.0:
            return {"status": "budget_exhausted"}
        self.budget -= 2.0
        if self.reject_communication:
            return {"status": "max_comm_reached"}
        if int(node["comm_left"]) <= 0:
            return {"status": "max_comm_reached"}
        node["comm_left"] = int(node["comm_left"]) - 1
        node["w"] = float(node["w"]) + 1.0
        return {"status": "success", "new_w": node["w"]}

    def cut_link(self, left: int, right: int) -> bool:
        self.calls.append(("cut", left, right))
        edge = (left, right) if left < right else (right, left)
        if self.budget < 3.0 or edge not in self.edges:
            return False
        self.budget -= 3.0
        self.edges.remove(edge)
        return True

    def shield_node(self, node_id: int) -> bool:
        self.calls.append(("shield", node_id))
        if self.budget < 5.0 or node_id not in self.nodes:
            return False
        self.budget -= 5.0
        del self.nodes[node_id]
        self.edges = {edge for edge in self.edges if node_id not in edge}
        return True


class RuntimeControllerIntegrationTests(unittest.TestCase):
    @staticmethod
    def _active_profile() -> CalibrationProfile:
        draft = CalibrationProfile(
            gate_passed=True,
            settlement_residual_std={"comm": 0.0, "cut": 0.0, "shield": 0.0},
            response_mean={"和平|1|1": 10.0, "中立|1|1": 10.0},
            response_std={"和平|1|1": 0.0, "中立|1|1": 0.0},
            manifest_hash="manifest",
            data_hash="data",
        )
        return CalibrationProfile(**{**asdict(draft), "profile_hash": draft.computed_hash()})

    def test_unverified_cmg_profile_is_exact_v0_fallback(self) -> None:
        left, right = FakeStarNetEnvironment(4, 60.0), FakeStarNetEnvironment(4, 60.0)
        v0 = RuntimeController(left, node_count=4, config=PolicyConfig(max_llm_calls=0))
        v1 = RuntimeController(
            right,
            node_count=4,
            config=PolicyConfig(max_llm_calls=0, policy_mode=PolicyMode.V1_CMG),
        )
        for _ in range(20):
            if not v0.stopped:
                v0.step()
            if not v1.stopped:
                v1.step()
        self.assertEqual(left.calls, right.calls)
        self.assertEqual(v1.llm_calls, 0)

    def test_unverified_b5_is_exact_b1_fallback_without_llm_calls(self) -> None:
        left, right = FakeStarNetEnvironment(4, 60.0), FakeStarNetEnvironment(4, 60.0)
        b1 = RuntimeController(
            left,
            node_count=4,
            config=PolicyConfig(
                policy_mode=PolicyMode.B1_PERSUASION,
                enable_shield=False,
                enable_cut=False,
                max_llm_calls=0,
            ),
        )
        llm_payloads: list[dict[str, object]] = []
        b5 = RuntimeController(
            right,
            llm_payloads.append,
            node_count=4,
            config=PolicyConfig(
                policy_mode=PolicyMode.B5_ADAPTIVE,
                max_llm_calls=5,
            ),
        )
        for _ in range(40):
            if not b1.stopped:
                b1.step()
            if not b5.stopped:
                b5.step()

        self.assertEqual(left.calls, right.calls)
        self.assertEqual(b5.llm_calls, 0)
        self.assertEqual(llm_payloads, [])
    def test_50_node_scan_is_fixed_cost_and_never_calls_llm(self) -> None:
        env = FakeStarNetEnvironment(50, 100.0)
        llm_payloads: list[dict[str, object]] = []
        controller = RuntimeController(env, llm_payloads.append)

        for _ in range(50):
            self.assertEqual(controller.step(), 0)

        self.assertEqual([call[1] for call in env.calls], list(range(1, 51)))
        self.assertEqual(env.budget, 75.0)
        self.assertEqual(controller.llm_calls, 0)
        self.assertEqual(llm_payloads, [])
        self.assertEqual(controller.state, ControllerState.ANALYZE)

    def test_public_experiment_uses_model_choice_for_each_scan_and_action(self) -> None:
        env = FakeStarNetEnvironment(4, 12.0)
        decisions: list[dict[str, object]] = []

        def choose(payload: dict[str, object]) -> dict[str, object]:
            decisions.append(payload)
            candidate = payload["candidates"][0]
            return {
                "state_version": payload["state_version"],
                "mode": "single_action",
                "candidate_id": candidate["candidate_id"],
                "reason_code": "public_gain",
                "evidence_ids": [candidate["evidence_ids"][0]],
            }

        controller = RuntimeController(
            env, choose, node_count=4,
            config=PolicyConfig(
                policy_mode=PolicyMode.PUBLIC_GREEDY,
                p0_exclusive=False, max_llm_calls=20,
            ),
        )
        while not controller.stopped:
            controller.step()
        self.assertEqual(len([call for call in env.calls if call[0] == "scan"]), 4)
        self.assertEqual(len([item for item in decisions if item["stage"] == "SCAN_ALL"]), 4)
        self.assertGreater(len(decisions), 4)
        self.assertEqual(controller.llm_calls, len(decisions))
        self.assertEqual(controller.action_failures, 0)

    def test_casevo_agent_chooses_scan_through_injected_llm(self) -> None:
        class StubLLM:
            class Embedding:
                def __call__(self, input: list[str]) -> list[list[float]]:
                    return [[0.0, 0.0, 0.0] for _ in input]

                def name(self) -> str:
                    return "test_disabled_embedding"

            def get_lang_embedding(self) -> "StubLLM.Embedding":
                return self.Embedding()

            def send_message(self, prompt: str, json_flag: bool = False) -> str:
                ids = ast.literal_eval(re.search(r"候选 ID：(\[[^\n]+\])", prompt).group(1))
                version = int(re.search(r"状态版本：(\d+)", prompt).group(1))
                return json.dumps({
                    "state_version": version, "mode": "single_action",
                    "candidate_id": ids[-1], "reason_code": "frontier_choice",
                    "evidence_ids": [ids[-1]],
                })

        env = FakeStarNetEnvironment(4, 12.0)
        model = ParticipantSquadModel(
            env, [{"role": "CommanderAgent", "experimental_policy_mode": "public_greedy"}],
            StubLLM(),
        )
        self.assertEqual(len(model.agent_list), 1)
        self.assertEqual(model.step(), 0)
        self.assertEqual(env.calls[-1], ("scan", 4))
        self.assertEqual(model.controller.llm_calls, 1)

    def test_public_scan_timeout_falls_back_and_counts_quota(self) -> None:
        env = FakeStarNetEnvironment(3, 10.0)

        def timed_out(_: dict[str, object]) -> object:
            raise TimeoutError("test timeout")

        controller = RuntimeController(
            env, timed_out, node_count=3,
            config=PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=1),
        )
        for _ in range(3):
            self.assertEqual(controller.step(), 0)
        self.assertEqual(controller.llm_calls, 1)
        self.assertEqual(controller.llm_accepted, 0)
        self.assertEqual(controller.llm_fallbacks, 1)
        self.assertEqual({call[1] for call in env.calls}, {1, 2, 3})
        self.assertEqual(controller.action_failures, 0)

    def test_failed_cut_refreshes_debited_public_budget(self) -> None:
        env = FakeStarNetEnvironment(2, 10.0)
        controller = RuntimeController(env, node_count=2)
        for node_id in (1, 2):
            controller.blackboard.record_scan(node_id, env.scan_node(node_id))

        def rejected_cut(left: int, right: int) -> bool:
            env.budget -= 3.0
            return False

        env.cut_link = rejected_cut  # type: ignore[method-assign]
        self.assertFalse(controller._attempt_action(Action("cut", 1, target_node_2=2), "cut:1-2", 9.0))
        self.assertEqual(env.get_remaining_budget(), 6.0)
        self.assertEqual(controller.blackboard.budget_units, 12)
        self.assertIn((1, 2), controller.blackboard.edges)

    def test_100_node_scan_uses_200_budget_tier(self) -> None:
        env = FakeStarNetEnvironment(100, 200.0)
        controller = RuntimeController(env, stage=ContestStage.FINAL)

        for _ in range(100):
            self.assertEqual(controller.step(), 0)

        scan_calls = [call for call in env.calls if call[0] == "scan"]
        self.assertEqual(len(scan_calls), 100)
        self.assertEqual(scan_calls[-1], ("scan", 100))
        self.assertEqual(env.budget, 150.0)
        self.assertEqual(controller.llm_calls, 0)

    def test_llm_failure_and_environment_rejections_fall_back_without_retries(self) -> None:
        env = FakeStarNetEnvironment(4, 100.0, reject_communication=True)

        def broken_ranker(_: dict[str, object]) -> object:
            raise TimeoutError("simulated timeout")

        controller = RuntimeController(env, broken_ranker, node_count=4)
        for _ in range(80):
            if controller.step() == 1:
                break

        self.assertTrue(controller.stopped)
        self.assertLessEqual(controller.llm_calls, 3)
        comm_calls = [call for call in env.calls if call[0] == "comm"]
        self.assertTrue(comm_calls)
        self.assertEqual(len(comm_calls), len({call[1] for call in comm_calls}))
        for _, node_id, _ in comm_calls:
            self.assertEqual(controller.blackboard.nodes[node_id].comm_left, 0)

    def test_no_candidates_records_stop_reason_and_action_counts(self) -> None:
        env = FakeStarNetEnvironment(1, 10.0)
        env.nodes[1]["persona"] = "暴力"
        env.nodes[1]["comm_left"] = 0
        controller = RuntimeController(env, node_count=1)

        self.assertEqual(controller.step(), 0)
        self.assertEqual(controller.step(), 1)

        self.assertEqual(controller.stop_reason, StopReason.NO_CANDIDATES)
        self.assertEqual(controller.action_attempts, 1)
        self.assertEqual(controller.action_successes, 1)
        self.assertEqual(controller.action_failures, 0)

    def test_action_exception_is_recorded_without_stopping_fallback_controller(self) -> None:
        env = FakeStarNetEnvironment(1, 10.0)

        def broken_scan(_: int) -> dict[str, object] | None:
            raise RuntimeError("simulated protocol failure")

        env.scan_node = broken_scan  # type: ignore[method-assign]
        controller = RuntimeController(env, node_count=1)

        self.assertEqual(controller.step(), 0)

        self.assertEqual(controller.last_action_error, "RuntimeError")
        self.assertEqual(controller.action_attempts, 1)
        self.assertEqual(controller.action_successes, 0)
        self.assertEqual(controller.action_failures, 1)

    def test_four_node_seed_reaches_commander_with_20_or_60_budget(self) -> None:
        for budget in (20.0, 60.0):
            with self.subTest(budget=budget):
                env = FakeStarNetEnvironment(4, budget)
                env.nodes[1].update(w=10.0, persona="和平", neighbors=[2, 4])
                env.nodes[2].update(w=-40.0, persona="暴力", neighbors=[1, 3])
                env.nodes[3].update(w=0.0, persona="中立", neighbors=[2, 4])
                env.nodes[4].update(w=15.0, persona="和平", neighbors=[1, 3])
                env.edges = {(1, 2), (2, 3), (3, 4), (1, 4)}
                payloads: list[dict[str, object]] = []

                def rank(payload: dict[str, object]) -> dict[str, object]:
                    payloads.append(payload)
                    return {"mode": "risk_first", "candidate_ids": ["shield:2"]}

                controller = RuntimeController(env, rank, node_count=4, config=PolicyConfig(max_llm_calls=3))
                for _ in range(5):
                    self.assertEqual(controller.step(), 0)

                self.assertEqual(controller.llm_calls, 1)
                self.assertEqual(len(payloads), 1)
                self.assertIn("shield:2", controller.candidates)
                self.assertIn(("shield", 2), env.calls)

    def test_commander_single_candidate_protocol_is_accepted(self) -> None:
        env = FakeStarNetEnvironment(4, 60.0)
        env.nodes[1].update(w=10.0, persona="和平", neighbors=[2, 4])
        env.nodes[2].update(w=-40.0, persona="暴力", neighbors=[1, 3])
        env.nodes[3].update(w=0.0, persona="中立", neighbors=[2, 4])
        env.nodes[4].update(w=15.0, persona="和平", neighbors=[1, 3])
        env.edges = {(1, 2), (2, 3), (3, 4), (1, 4)}
        payloads: list[dict[str, object]] = []

        def rank(payload: dict[str, object]) -> dict[str, object]:
            payloads.append(payload)
            self.assertIn("state_version", payload)
            self.assertIn("candidate_ids", payload)
            self.assertIn("shield:2", payload["candidate_ids"])
            return {
                "state_version": payload["state_version"],
                "mode": "single_action",
                "candidate_id": "shield:2",
                "reason_code": "risk",
                "evidence_ids": ["shield:2"],
            }

        controller = RuntimeController(env, rank, node_count=4, config=PolicyConfig(max_llm_calls=1))
        for _ in range(5):
            controller.step()
        self.assertEqual(controller.llm_calls, 1)
        self.assertEqual(len(payloads), 1)
        self.assertIn(("shield", 2), env.calls)


if __name__ == "__main__":
    unittest.main()

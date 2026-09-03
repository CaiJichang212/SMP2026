"""运行时状态机的模拟环境集成测试。"""

from __future__ import annotations

import unittest

from starnet.runtime.controller import ControllerState, RuntimeController


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

    def test_100_node_scan_uses_200_budget_tier(self) -> None:
        env = FakeStarNetEnvironment(100, 200.0)
        controller = RuntimeController(env)

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


if __name__ == "__main__":
    unittest.main()

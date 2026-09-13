"""Exactness and cache-bound checks for the topology settlement experiment."""

from __future__ import annotations

import random
import unittest

from starnet.model.blackboard import NodeState
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.cmg import PredictiveState, SettlementPredictor
from starnet.policy.fast_settlement_experiment import FastComponentSettlement


class FastSettlementExperimentTests(unittest.TestCase):
    def test_prepared_structure_scores_match_copied_state(self):
        from starnet.model.blackboard import Blackboard
        from starnet.policy.actions import Action
        from starnet.policy.cmg import PredictiveState, SettlementPredictor
        from starnet.policy.calibration import CalibrationProfile
        import random
        rng = random.Random(20260913)
        engine = FastComponentSettlement()
        reference = SettlementPredictor(CalibrationProfile(gate_passed=False, model="component_degree_plus_one"))
        for trial in range(100):
            count = rng.randrange(2, 25)
            board = Blackboard(count)
            edges = {(left, right) for left in range(1, count + 1)
                     for right in range(left + 1, count + 1) if rng.random() < .2}
            for node in range(1, count + 1):
                board.record_scan(node, {"w": rng.uniform(-40, 30), "persona": "中立", "comm_left": 3,
                                         "neighbors": sorted(b if a == node else a for a, b in edges if node in (a, b))})
            state = PredictiveState.from_blackboard(board)
            prepared = engine.prepare(state)
            self.assertEqual(prepared.score(), reference.score(state))
            actions = [Action("shield", 1), Action("shield", count)]
            actions += [Action("cut", a, target_node_2=b) for a, b in sorted(edges)[:2]]
            for action in actions:
                self.assertEqual(prepared.score_after(action), reference.score(state.apply(action)))
            self.assertLessEqual(len(engine._action_cache), 16)

    def test_hundreds_of_random_states_match_exactly(self) -> None:
        rng = random.Random(20260913)
        reference = SettlementPredictor(
            CalibrationProfile(gate_passed=False, model="component_degree_plus_one")
        )
        fast = FastComponentSettlement()
        for _ in range(400):
            count = rng.randint(1, 45)
            nodes = {
                node: NodeState(rng.uniform(-80.0, 80.0), "中立", rng.randint(0, 3))
                for node in range(1, count + 1)
                if rng.random() > 0.08
            }
            edges = {
                (left, right)
                for left in nodes for right in nodes
                if left < right and rng.random() < 0.09
            }
            state = PredictiveState(nodes, edges, set(range(1, count + 1)) - set(nodes))
            self.assertEqual(fast.score(state), reference.score(state))

    def test_opinions_are_absent_from_key_and_recomputed_on_hit(self) -> None:
        first = PredictiveState(
            {1: NodeState(-10.0, "暴力", 3), 2: NodeState(20.0, "和平", 3)},
            {(1, 2)}, set(),
        )
        second = PredictiveState(
            {1: NodeState(30.0, "暴力", 1), 2: NodeState(-5.0, "和平", 2)},
            {(1, 2)}, set(),
        )
        fast = FastComponentSettlement()
        self.assertEqual(fast.topology_key(first), fast.topology_key(second))
        first_score = fast.score(first)
        second_score = fast.score(second)
        self.assertNotEqual(first_score, second_score)
        self.assertEqual((fast.misses, fast.hits, fast.cache_size), (1, 1, 1))

    def test_lru_never_exceeds_declared_capacity(self) -> None:
        fast = FastComponentSettlement(max_topologies=8)
        for count in range(1, 25):
            nodes = {node: NodeState(float(node), "中立", 3) for node in range(1, count + 1)}
            state = PredictiveState(nodes, set(), set())
            fast.score(state)
            self.assertLessEqual(fast.cache_size, 8)
        self.assertEqual(fast.cache_size, 8)
        self.assertEqual(fast.misses, 24)

    def test_invalid_capacity_is_rejected(self) -> None:
        for value in (0, -1, False):
            with self.assertRaises(ValueError):
                FastComponentSettlement(value)


if __name__ == "__main__":
    unittest.main()

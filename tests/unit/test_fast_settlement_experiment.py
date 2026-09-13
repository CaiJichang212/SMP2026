"""Exactness and cache-bound checks for the topology settlement experiment."""

from __future__ import annotations

import random
import unittest

from starnet.model.blackboard import NodeState
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.cmg import PredictiveState, SettlementPredictor
from starnet.policy.fast_settlement_experiment import FastComponentSettlement


class FastSettlementExperimentTests(unittest.TestCase):
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

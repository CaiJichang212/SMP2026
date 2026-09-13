from __future__ import annotations

import itertools
import unittest
from unittest.mock import patch

import networkx as nx

from starnet.model.blackboard import Blackboard, NodeState
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.budget_experiment import budget_plan, communication_tail
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.cmg import PredictiveState, SettlementPredictor


class BudgetExperimentTests(unittest.TestCase):
    def setUp(self):
        self.board = Blackboard(node_count=4)
        for node_id, weight in enumerate((-30.0, 8.0, 12.0, -10.0), 1):
            self.board.record_scan(node_id, {"w": weight, "persona": "中立", "comm_left": 3,
                                            "neighbors": [n for n in range(1, 5) if n != node_id and (n == 1 or node_id == 1)]})
        self.predictor = SettlementPredictor(CalibrationProfile(gate_passed=False, model="component_degree_plus_one"))

    @staticmethod
    def response(node_id, node, turn):
        return (node_id + 3.0) * 0.5 ** (turn - 1)

    def test_allocator_matches_exhaustive_prefix_allocations(self):
        state = PredictiveState.from_blackboard(self.board)
        for slots in range(7):
            oracle = float("-inf")
            for counts in itertools.product(range(4), repeat=4):
                if sum(counts) > slots:
                    continue
                nodes = {node_id: NodeState(node.w + sum(self.response(node_id, node, turn) for turn in range(1, counts[node_id - 1] + 1)),
                                           node.persona, node.comm_left - counts[node_id - 1])
                         for node_id, node in state.nodes.items()}
                oracle = max(oracle, self.predictor.score(PredictiveState(nodes, state.edges, set())))
            plan = communication_tail(state, slots * 2 + 1, self.response, 100)
            self.assertAlmostEqual(plan.score, oracle)
            self.assertLessEqual(len(plan.actions), slots)
            scored = communication_tail(state, slots * 2 + 1, self.response, 100, include_actions=False)
            self.assertEqual(scored.score, plan.score)
            self.assertEqual(scored.actions, ())

    def test_plan_replays_with_budget_and_preserves_public_facts(self):
        original = PredictiveState.from_blackboard(self.board)
        plan = budget_plan(self.board, 13, self.response, remaining_steps=5, depth=2)
        state = original
        spent = 0
        for action in plan.actions:
            if action.kind == "comm":
                node = state.nodes[action.target_node_1]
                delta = self.response(action.target_node_1, node, 4 - node.comm_left)
            else:
                delta = None
            state = state.apply(action, delta)
            spent += action_cost(action)
        self.assertLessEqual(spent, 13)
        self.assertLessEqual(len(plan.actions), 5)
        self.assertAlmostEqual(plan.score, self.predictor.score(state))
        self.assertEqual(original, PredictiveState.from_blackboard(self.board))
        self.assertTrue(is_legal_action(plan.actions[0], self.board, 13))

    def test_step_limit_and_invalid_response_fail_closed(self):
        state = PredictiveState.from_blackboard(self.board)
        self.assertEqual(communication_tail(state, 100, self.response, 0).actions, ())
        for response in (lambda *_: float("nan"), lambda *_: -1, lambda _, __, turn: turn):
            with self.assertRaises(ValueError):
                communication_tail(state, 10, response, 5)

    def test_allocator_consumes_opinion_space_across_slots(self):
        board = Blackboard(node_count=1)
        board.record_scan(1, {"w": 95.0, "persona": "和平", "comm_left": 3, "neighbors": []})
        state = PredictiveState.from_blackboard(board)
        plan = communication_tail(state, 20.0, lambda *_: 15.0, 10)
        self.assertEqual(plan.score, 100.0)
        self.assertEqual(plan.actions, (Action("comm", 1, prompt_id=1),))

    def test_positive_graph_keeps_structure_gate_closed(self):
        for node in self.board.nodes.values():
            node.w = 20.0
            node.persona = "和平"
        plan = budget_plan(self.board, 15, self.response, remaining_steps=10)
        self.assertTrue(all(action.kind == "comm" for action in plan.actions))

    def test_connected_fast_path_matches_general_component_search(self):
        for graph in (nx.cycle_graph(7), nx.complete_graph(7), nx.path_graph(7), nx.gnp_random_graph(7, 0.4, seed=31)):
            board = Blackboard(node_count=7)
            for node_id in graph:
                board.record_scan(node_id + 1, {"w": -20.0 if node_id % 2 == 0 else 10.0,
                    "persona": "中立", "comm_left": 3, "neighbors": [neighbor + 1 for neighbor in graph[node_id]]})
            fast = budget_plan(board, 17, self.response, remaining_steps=8)
            with patch("starnet.policy.budget_experiment.nx.is_connected", return_value=False):
                general = budget_plan(board, 17, self.response, remaining_steps=8)
            self.assertEqual(fast.actions, general.actions)
            self.assertEqual(fast.score, general.score)

    def test_connected_fast_path_matches_general_at_opinion_bound(self):
        graph = nx.cycle_graph(6)
        board = Blackboard(node_count=6)
        for zero_id in graph:
            board.record_scan(zero_id + 1, {
                "w": -30.0 if zero_id == 0 else 95.0,
                "persona": "暴力" if zero_id == 0 else "和平",
                "comm_left": 3,
                "neighbors": [neighbor + 1 for neighbor in graph[zero_id]],
            })
        response = lambda _node_id, _node, turn: 15.0 * 0.5 ** (turn - 1)
        fast = budget_plan(board, 17, response, remaining_steps=8)
        with patch("starnet.policy.budget_experiment.nx.is_connected", return_value=False):
            general = budget_plan(board, 17, response, remaining_steps=8)
        self.assertEqual(fast.actions, general.actions)
        self.assertEqual(fast.score, general.score)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import math
import random
import unittest
from unittest.mock import patch

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.budget_experiment import BudgetPlan
from starnet.policy.candidates import Candidate
from starnet.policy.p8_experiment import (
    _candidate_domain, _greedy_candidates, _rollout, _scenario_factor,
    choose_p8_action, public_board_salt,
)


def make_board() -> Blackboard:
    board = Blackboard(node_count=3)
    for node_id, weight in enumerate((-30.0, 8.0, 12.0), 1):
        board.record_scan(node_id, {
            "w": weight, "persona": "暴力" if node_id == 1 else "和平",
            "comm_left": 3,
            "neighbors": [other for other in range(1, 4) if other != node_id],
        })
    return board


def candidate(action: Action, score: float, roi: float, name: str) -> Candidate:
    return Candidate(name, action, 0, score, roi, "test")


class P8ExperimentTests(unittest.TestCase):
    def test_salt_requires_complete_board_and_binds_scenarios_to_public_state(self):
        partial = Blackboard(node_count=2)
        partial.record_scan(1, {"w": 1, "persona": "中立", "comm_left": 3, "neighbors": []})
        with self.assertRaises(ValueError):
            public_board_salt(partial)
        first = make_board()
        second = make_board()
        second.nodes[3].w += 0.25
        first_salt, second_salt = public_board_salt(first), public_board_salt(second)
        self.assertNotEqual(first_salt, second_salt)
        self.assertNotEqual(_scenario_factor(first_salt, 2, 1),
                            _scenario_factor(second_salt, 2, 1))

    def test_antithetic_pairs_and_uniform_bounds(self):
        salt = "a" * 64
        self.assertEqual(_scenario_factor(salt, 3, 0), 0.85)
        for left, right in ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12)):
            values = (_scenario_factor(salt, 3, left), _scenario_factor(salt, 3, right))
            self.assertTrue(all(0.2 <= value <= 1.5 for value in values))
            self.assertAlmostEqual(sum(values), 1.7)

    def test_fast_planner_matches_reference_candidates_on_random_public_states(self):
        rng = random.Random(20260913)
        for _ in range(240):
            count = rng.randint(5, 10)
            edges = {(left, right) for left in range(1, count + 1)
                     for right in range(left + 1, count + 1) if rng.random() < 0.28}
            neighbors = {node: [] for node in range(1, count + 1)}
            for left, right in edges:
                neighbors[left].append(right)
                neighbors[right].append(left)
            board = Blackboard(node_count=count)
            observed = {}
            for node_id in range(1, count + 1):
                comm_left = rng.randint(1, 3)
                board.record_scan(node_id, {
                    "w": rng.uniform(-40, 30),
                    "persona": rng.choice(("和平", "中立", "暴力")),
                    "comm_left": comm_left, "neighbors": neighbors[node_id],
                })
                if comm_left < 3:
                    observed[node_id] = rng.uniform(3, 22)
            budget = rng.choice((2.0, 3.0, 5.0, 9.0, 20.0))
            self.assertEqual(
                _greedy_candidates(board, budget, observed, fast=True),
                _greedy_candidates(board, budget, observed, fast=False),
            )

    def test_domain_adds_untried_comm_and_stays_bounded(self):
        board = make_board()
        baseline = candidate(Action("shield", 1), 30, 6, "shield:1")
        immediate = candidate(Action("cut", 1, target_node_2=2), 20, 5, "cut:1-2")
        tried = candidate(Action("comm", 2, prompt_id=1), 18, 9, "comm:2:1")
        untried = candidate(Action("comm", 3, prompt_id=1), 16, 8, "comm:3:1")
        with patch("starnet.policy.p8_experiment._greedy_candidates",
                   return_value=[baseline, immediate, tried, untried]), \
             patch("starnet.policy.p8_experiment.budget_plan",
                   return_value=BudgetPlan(1, (Action("cut", 1, target_node_2=3),))):
            domain = _candidate_domain(board, 20, {2: 12.0}, 5)
        self.assertEqual(len(domain), 3)
        self.assertIn((Action("cut", 1, target_node_2=3), "p7_budget_structure"), domain)
        self.assertIn((Action("comm", 3, prompt_id=1), "untried_comm_roi"), domain)
        self.assertNotIn((Action("comm", 2, prompt_id=1), "untried_comm_roi"), domain)

    def test_expected_and_conservative_share_cache_but_apply_distinct_gate(self):
        board = make_board()
        baseline, alternative = Action("comm", 2, prompt_id=1), Action("comm", 3, prompt_id=1)
        domain = ((baseline, "public_greedy"), (alternative, "untried_comm_roi"))
        deltas = (1.0, -3.0, 1.0, 1.0, 1.0)

        def score(_board, _budget, _observed, action, _steps, *, scenario, salt):
            return 100.0 if action == baseline else 100.0 + deltas[scenario]

        cache = {}
        with patch("starnet.policy.p8_experiment._candidate_domain", return_value=domain), \
             patch("starnet.policy.p8_experiment._rollout", side_effect=score):
            expected = choose_p8_action(board, 10, {}, remaining_steps=4,
                                        salt="b" * 64, mode="expected", evaluation_cache=cache)
            conservative = choose_p8_action(board, 10, {}, remaining_steps=4,
                                            salt="b" * 64, mode="conservative", evaluation_cache=cache)
        self.assertEqual(expected.action, alternative)
        self.assertTrue(expected.deviated)
        self.assertEqual(conservative.action, baseline)
        self.assertEqual(expected.rollouts, 10)
        self.assertEqual(conservative.rollouts, 0)
        self.assertAlmostEqual(expected.mean_delta, 0.2)
        self.assertEqual(expected.minimum_delta, -3.0)

    def test_untried_comm_bypasses_neutral_mean_screen_for_information_value(self):
        board = make_board()
        baseline, comm = Action("shield", 1), Action("comm", 3, prompt_id=1)
        domain = ((baseline, "public_greedy"), (comm, "untried_comm_roi"))
        deltas = (0.0, 2.0, 2.0, 2.0, 2.0)

        def score(_board, _budget, _observed, action, _steps, *, scenario, salt):
            return 50.0 if action == baseline else 50.0 + deltas[scenario]

        with patch("starnet.policy.p8_experiment._candidate_domain", return_value=domain), \
             patch("starnet.policy.p8_experiment._rollout", side_effect=score):
            decision = choose_p8_action(board, 10, {}, remaining_steps=4,
                                        salt="d" * 64, mode="expected")
        self.assertEqual(decision.action, comm)
        self.assertAlmostEqual(decision.mean_delta, 1.6)

    def test_conservative_selects_safe_second_finalist(self):
        board = make_board()
        baseline = Action("comm", 2, prompt_id=1)
        unsafe = Action("shield", 1)
        safe = Action("comm", 3, prompt_id=1)
        domain = ((baseline, "public_greedy"),
                  (unsafe, "immediate_structure_gain"),
                  (safe, "untried_comm_roi"))
        by_action = {
            baseline: (0.0,) * 5,
            unsafe: (4.0, -1.0, 4.0, 4.0, 4.0),
            safe: (2.0,) * 5,
        }

        def score(_board, _budget, _observed, action, _steps, *, scenario, salt):
            return 100.0 + by_action[action][scenario]

        cache = {}
        with patch("starnet.policy.p8_experiment._candidate_domain", return_value=domain), \
             patch("starnet.policy.p8_experiment._rollout", side_effect=score):
            expected = choose_p8_action(board, 10, {}, remaining_steps=4,
                                        salt="e" * 64, mode="expected", evaluation_cache=cache)
            conservative = choose_p8_action(board, 10, {}, remaining_steps=4,
                                            salt="e" * 64, mode="conservative", evaluation_cache=cache)
        self.assertEqual(expected.action, unsafe)
        self.assertEqual(conservative.action, safe)
        self.assertEqual(expected.rollouts, 15)
        self.assertEqual(conservative.rollouts, 0)

    def test_audited_uses_independent_scenarios_and_does_not_reselect(self):
        board = make_board()
        baseline, winner = Action("comm", 2, prompt_id=1), Action("shield", 1)
        domain = ((baseline, "public_greedy"), (winner, "p7_budget_structure"))

        def score(_board, _budget, _observed, action, _steps, *, scenario, salt):
            if action == baseline:
                return 100.0
            return 102.0 if scenario < 12 else 99.0

        with patch("starnet.policy.p8_experiment._candidate_domain", return_value=domain), \
             patch("starnet.policy.p8_experiment._rollout", side_effect=score):
            decision = choose_p8_action(board, 10, {}, remaining_steps=4,
                                        salt="f" * 64, mode="audited")
        self.assertEqual(decision.proposed_action, winner)
        self.assertEqual(decision.action, baseline)
        self.assertFalse(decision.deviated)
        self.assertEqual(len(decision.audit_paired_deltas), 8)
        self.assertEqual(decision.audit_minimum_delta, -1.0)
        self.assertEqual(decision.rollouts, 26)

    def test_audited_accepts_same_winner_when_extra_pair_gate_passes(self):
        board = make_board()
        baseline, winner = Action("comm", 2, prompt_id=1), Action("shield", 1)
        domain = ((baseline, "public_greedy"), (winner, "p7_budget_structure"))

        def score(_board, _budget, _observed, action, _steps, *, scenario, salt):
            return 100.0 if action == baseline else 101.0

        with patch("starnet.policy.p8_experiment._candidate_domain", return_value=domain), \
             patch("starnet.policy.p8_experiment._rollout", side_effect=score):
            decision = choose_p8_action(board, 10, {}, remaining_steps=4,
                                        salt="1" * 64, mode="audited")
        self.assertEqual(decision.action, winner)
        self.assertEqual(decision.audit_mean_delta, 1.0)
        self.assertEqual(decision.audit_minimum_delta, 1.0)

    def test_simulation_reveals_unknown_only_after_success_and_never_records_facts(self):
        board = make_board()
        calls = []

        def stop(projected, budget, observed):
            calls.append(dict(observed))
            return []

        with patch("starnet.policy.p8_experiment._greedy_candidates", side_effect=stop), \
             patch("starnet.policy.p8_experiment._scenario_factor", return_value=1.5), \
             patch.object(Blackboard, "record_communication",
                          side_effect=AssertionError("hypothesis entered Blackboard")):
            _rollout(board, 4, {}, Action("comm", 2, prompt_id=1), 2,
                     scenario=1, salt="c" * 64)
        self.assertEqual(calls, [{2: 22.5}])
        self.assertEqual(board.nodes[2].w, 8.0)

    def test_simulation_records_realized_first_delta_after_clipping(self):
        board = make_board()
        board.nodes[2].w = 95.0
        calls = []

        def stop(projected, budget, observed):
            calls.append(dict(observed))
            return []

        with patch("starnet.policy.p8_experiment._greedy_candidates", side_effect=stop), \
             patch("starnet.policy.p8_experiment._scenario_factor", return_value=1.5):
            _rollout(board, 4, {}, Action("comm", 2, prompt_id=1), 2,
                     scenario=1, salt="c" * 64)
        self.assertEqual(calls, [{2: 5.0}])
        self.assertEqual(board.nodes[2].w, 95.0)

    def test_invalid_or_nonfinite_inputs_fail_closed(self):
        board = make_board()
        salt = public_board_salt(board)
        for remaining, budget, observed in ((-1, 5, {}), (1, math.nan, {}), (1, 5, {1: math.inf})):
            with self.assertRaises(ValueError):
                choose_p8_action(board, budget, observed, remaining_steps=remaining,
                                 salt=salt, mode="expected")


if __name__ == "__main__":
    unittest.main()

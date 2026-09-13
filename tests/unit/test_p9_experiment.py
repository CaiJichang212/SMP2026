from __future__ import annotations

import unittest
from unittest.mock import patch

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.budget_experiment import BudgetPlan
from starnet.policy.candidates import Candidate
from starnet.policy.p9_experiment import candidate_domain, choose_p9_action


def board() -> Blackboard:
    result = Blackboard(node_count=3)
    for node_id, weight in enumerate((-20.0, 5.0, 10.0), 1):
        result.record_scan(node_id, {
            "w": weight,
            "persona": "暴力" if node_id == 1 else "和平",
            "comm_left": 3,
            "neighbors": [other for other in range(1, 4) if other != node_id],
        })
    return result


def item(action: Action, score: float, roi: float, name: str) -> Candidate:
    return Candidate(name, action, 0, score, roi, "test")


class P9ExperimentTests(unittest.TestCase):
    def test_portfolio_domain_is_class_balanced_and_includes_known_response(self):
        ranked = [
            item(Action("comm", 1, prompt_id=1), 30, 15, "baseline"),
            item(Action("shield", 1), 28, 5.6, "shield"),
            item(Action("cut", 1, target_node_2=2), 27, 9, "cut"),
            item(Action("comm", 2, prompt_id=1), 26, 13, "untried"),
            item(Action("comm", 3, prompt_id=1), 24, 12, "known"),
            item(Action("comm", 3, prompt_id=2), 20, 10, "known-second"),
        ]
        with patch("starnet.policy.p9_experiment._greedy_candidates", return_value=ranked), \
             patch("starnet.policy.p9_experiment.budget_plan", return_value=BudgetPlan(0, ())):
            domain = candidate_domain(board(), 20, {1: 10.0, 3: 8.0}, 5, "portfolio")
        sources = {source for _, source in domain}
        self.assertIn("immediate_shield", sources)
        self.assertIn("immediate_cut", sources)
        self.assertIn("untried_comm_roi", sources)
        self.assertIn("observed_comm_roi", sources)
        self.assertLessEqual(len(domain), 8)

    def test_conservative_rule_can_select_second_structure_candidate(self):
        baseline = Action("comm", 1, prompt_id=1)
        unsafe = Action("shield", 1)
        safe = Action("cut", 1, target_node_2=2)
        domain = ((baseline, "public_greedy"), (unsafe, "immediate_shield"), (safe, "immediate_cut"))
        values = {baseline: (0, 0, 0, 0, 0), unsafe: (5, -1, 5, 5, 5), safe: (2, 2, 2, 2, 2)}

        def rollout(_board, _budget, _observed, action, _steps, *, scenario, salt):
            return 100 + values[action][scenario]

        with patch("starnet.policy.p9_experiment.candidate_domain", return_value=domain), \
             patch("starnet.policy.p9_experiment._rollout", side_effect=rollout):
            decision = choose_p9_action(
                board(), 10, {}, remaining_steps=4, salt="a" * 64, variant="portfolio"
            )
        self.assertEqual(decision.action, safe)
        self.assertEqual(decision.source, "immediate_cut")
        self.assertLessEqual(decision.rollouts, 15)


if __name__ == "__main__":
    unittest.main()

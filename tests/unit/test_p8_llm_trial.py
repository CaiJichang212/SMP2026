"""Keep model choice and fallback legal for terminal-value trial candidates."""

import unittest
from unittest.mock import patch

from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p8_llm_trial import P8TrialController
from starnet.policy.actions import Action
from starnet.policy.config import PolicyConfig, PolicyMode
from starnet.policy.p8_experiment import P8Decision
from starnet.runtime.env_adapter import apply_action_outcome


class P8LLMTrialTests(unittest.TestCase):
    def controller(self, ranker):
        seed = {"global_setting": {"max_budget": 20}, "nodes": [
            {"id": node, "w": weight, "persona": persona, "comm_left": 3, "r": 1.0}
            for node, weight, persona in ((1, -40, "暴力"), (2, 10, "和平"), (3, 10, "和平"))],
                "edges": [[1, 2], [1, 3]]}
        env = LocalPublicEnvironment(seed)
        config = PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=10)
        controller = P8TrialController(env, ranker, node_count=3, config=config)
        for node in (1, 2, 3):
            apply_action_outcome(env, controller.blackboard, Action("scan", node), env.get_remaining_budget())
        return env, controller

    def decision(self):
        return P8Decision(Action("comm", 2, prompt_id=1), Action("shield", 1),
                          "untried_comm_roi", (), (2.0,) * 5, 2.0, 2.0, 0,
                          audit_paired_deltas=(1.0,) * 8, audit_mean_delta=1.0,
                          audit_minimum_delta=1.0)

    def test_llm_can_choose_baseline_instead_of_recommendation(self):
        def choose_baseline(payload):
            option = payload["candidates"][-1]
            return {"state_version": payload["state_version"], "mode": "single_action",
                    "candidate_id": option["candidate_id"], "reason_code": "baseline",
                    "evidence_ids": [option["evidence_ids"][0]]}
        env, controller = self.controller(choose_baseline)
        with patch("scripts.run_p8_llm_trial.choose_p8_action", return_value=self.decision()):
            controller._refresh_candidates(env.get_remaining_budget(), "test")
        self.assertTrue(controller.p8_options)
        self.assertEqual(len(controller._llm_candidate_options(list(controller.candidates.values()))), 2)
        controller._create_plan(env.get_remaining_budget())
        self.assertEqual(controller.candidates[controller.queue[0]].action, Action("shield", 1))
        self.assertEqual(controller.llm_calls, 1)
        self.assertEqual(controller.llm_accepted, 1)

    def test_invalid_llm_response_counts_and_uses_validated_recommendation(self):
        env, controller = self.controller(lambda _: {"candidate_id": "invalid"})
        with patch("scripts.run_p8_llm_trial.choose_p8_action", return_value=self.decision()):
            controller._refresh_candidates(env.get_remaining_budget(), "test")
        controller._create_plan(env.get_remaining_budget())
        self.assertEqual(controller.candidates[controller.queue[0]].action, Action("comm", 2, prompt_id=1))
        self.assertEqual(controller.llm_calls, 1)
        self.assertEqual(controller.llm_fallbacks, 1)

    def test_planning_error_preserves_baseline_and_public_facts(self):
        env, controller = self.controller(None)
        before = controller.blackboard.snapshot()
        with patch("scripts.run_p8_llm_trial.choose_p8_action", side_effect=TimeoutError):
            controller._refresh_candidates(env.get_remaining_budget(), "test")
        self.assertFalse(controller.p8_options)
        self.assertEqual(controller.p8_planning_errors, 1)
        self.assertEqual(next(iter(controller.candidates.values())).action, Action("shield", 1))
        self.assertEqual(before, controller.blackboard.snapshot())


if __name__ == "__main__":
    unittest.main()

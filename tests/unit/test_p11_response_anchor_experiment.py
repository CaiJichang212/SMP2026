"""Runtime checks for the selected-prompt response-anchor experiment."""

import unittest

from starnet.policy.config import PolicyConfig, PolicyMode
from starnet.runtime.p11_response_anchor_experiment import AnchoredPromptLearningController
from tests.unit.test_p11_prompt_controller import PromptEnvironment, valid_first


class P11ResponseAnchorExperimentTests(unittest.TestCase):
    def controller(self, strengths, *, ranker=valid_first):
        env = PromptEnvironment(strengths, factors=(1.0, 0.5, 0.6))
        controller = AnchoredPromptLearningController(
            env, ranker, node_count=3, p8_mode="conservative",
            config=PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=30),
            max_probe_budget=6.0, max_probe_nodes=1,
        )
        return env, controller

    def drive_anchor(self, env, controller):
        for _ in range(20):
            before = len(env.calls)
            controller.step()
            self.assertLessEqual(len(env.calls) - before, 1)
            if controller.p11_anchor_finished:
                return
        self.fail("P11 response anchor did not finish")

    def test_anchor_excludes_identification_probe_from_transfer_prior(self):
        env, controller = self.controller((-5.0, 15.0, 10.0))
        self.drive_anchor(env, controller)
        self.assertEqual(controller.p11_probe_nodes, (1,))
        self.assertEqual(controller.p11_probe_budget, 6.0)
        self.assertEqual(controller.p11_selected_prompt_id, 2)
        self.assertEqual(controller.p11_anchor_target, 2)
        self.assertEqual(controller.p11_anchor_budget, 2.0)
        self.assertTrue(controller.p11_anchor_used)
        self.assertEqual(controller.p11_selected_prompt_probe_values, (15.0,))
        self.assertEqual(controller.p11_selected_prompt_observations, {2: 7.5})
        self.assertEqual(controller.p11_selected_prompt_prior, 7.5)
        self.assertEqual(env.calls[3:7], [
            ("comm", 1, 1), ("comm", 1, 2), ("comm", 1, 3), ("comm", 2, 2),
        ])

    def test_invalid_llm_output_still_executes_legal_anchor(self):
        env, controller = self.controller(
            (-5.0, 15.0, 10.0), ranker=lambda _: {"invalid": True},
        )
        self.drive_anchor(env, controller)
        self.assertTrue(controller.p11_anchor_used)
        self.assertEqual(controller.p11_anchor_attempts, 1)
        self.assertEqual(controller.p11_anchor_successes, 1)
        self.assertGreaterEqual(controller.llm_fallbacks, 4)

    def test_nonpositive_best_skips_anchor_and_keeps_frozen_prior(self):
        env, controller = self.controller((-5.0, -2.0, -4.0))
        self.drive_anchor(env, controller)
        self.assertFalse(controller.p11_anchor_used)
        self.assertEqual(controller.p11_anchor_attempts, 0)
        self.assertEqual(controller.p11_anchor_budget, 0.0)
        self.assertEqual(controller.p11_anchor_skip_reason, "nonpositive_or_missing_prompt")
        self.assertEqual(controller.p11_selected_prompt_prior, -2.0)

    def test_second_probe_node_plus_anchor_is_bounded_at_fourteen(self):
        env = PromptEnvironment((-5.0, 15.0, 10.0), factors=(0.0, 1.0, 0.6))
        controller = AnchoredPromptLearningController(
            env, valid_first, node_count=3, p8_mode="conservative",
            config=PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=30),
            max_probe_budget=12.0, max_probe_nodes=2,
        )
        self.drive_anchor(env, controller)
        self.assertEqual(controller.p11_probe_nodes, (1, 2))
        self.assertEqual(controller.p11_probe_budget, 12.0)
        self.assertEqual(controller.p11_anchor_target, 3)
        self.assertEqual(controller.p11_anchor_budget, 2.0)
        self.assertEqual(controller.p11_probe_budget + controller.p11_anchor_budget, 14.0)


if __name__ == "__main__":
    unittest.main()

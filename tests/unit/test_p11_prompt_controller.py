"""Runtime semantics for public-feedback prompt learning."""

import unittest
from unittest.mock import patch

from starnet.policy.config import PolicyConfig, PolicyMode
from starnet.runtime.p11_prompt_controller_experiment import PromptLearningRuntimeController


class PromptEnvironment:
    def __init__(self, strengths, factors=(1.0, 0.8, 0.6), *, fail=None):
        self.budget = 40.0
        self.strengths = dict(enumerate(strengths, 1))
        self.factors = dict(enumerate(factors, 1))
        self.fail = fail
        self.calls = []
        self.nodes = {
            node_id: {"w": float(node_id - 1), "persona": "和平", "comm_left": 3,
                      "neighbors": []}
            for node_id in range(1, 4)
        }

    def get_remaining_budget(self):
        return self.budget

    def scan_node(self, node_id):
        self.calls.append(("scan", node_id))
        self.budget -= 0.5
        return dict(self.nodes[node_id])

    def communicate(self, node_id, prompt_id):
        self.calls.append(("comm", node_id, prompt_id))
        if self.fail == (node_id, prompt_id):
            return {"status": "rejected"}
        self.budget -= 2.0
        node = self.nodes[node_id]
        turn = 4 - node["comm_left"]
        delta = self.strengths[prompt_id] * self.factors[node_id] * (0.5 ** (turn - 1))
        node["w"] = max(-100.0, min(100.0, node["w"] + delta))
        node["comm_left"] -= 1
        return {"status": "success", "new_w": node["w"], "comm_left": node["comm_left"]}

    def cut_link(self, left, right):
        self.calls.append(("cut", left, right))
        self.budget -= 3.0
        return False

    def shield_node(self, node_id):
        self.calls.append(("shield", node_id))
        self.budget -= 5.0
        if node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        return True


def valid_first(payload):
    item = payload["candidates"][0]
    return {
        "state_version": payload["state_version"], "mode": "single_action",
        "candidate_id": item["candidate_id"], "reason_code": "test",
        "evidence_ids": [item["evidence_ids"][0]],
    }


class PromptLearningRuntimeTests(unittest.TestCase):
    def controller(self, strengths, factors=(1.0, 0.8, 0.6), *, ranker=valid_first, fail=None):
        env = PromptEnvironment(strengths, factors, fail=fail)
        config = PolicyConfig(
            policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=60,
        )
        controller = PromptLearningRuntimeController(
            env, ranker, node_count=3, config=config, p8_mode="conservative",
            max_probe_budget=12.0, max_probe_nodes=2,
        )
        return env, controller

    def drive_calibration(self, env, controller):
        for _ in range(20):
            before = len(env.calls)
            controller.step()
            self.assertLessEqual(len(env.calls) - before, 1)
            if controller.p11_calibration_finished:
                return
        self.fail("prompt calibration did not finish")

    def test_one_informative_node_selects_prompt_and_updates_public_prior(self):
        env, controller = self.controller((-5.0, 15.0, 10.0), factors=(1.0, 0.5, 0.6))
        self.drive_calibration(env, controller)
        self.assertEqual(env.calls[3:6], [("comm", 1, 1), ("comm", 1, 2), ("comm", 1, 3)])
        self.assertEqual(controller.p11_selected_prompt_id, 2)
        self.assertEqual(controller.p11_selected_prompt_prior, 15.0)
        self.assertEqual(controller.p11_probe_budget, 6.0)
        self.assertFalse(controller.p11_prompt_ledger.confident)
        controller.step()
        self.assertEqual(env.calls[-1][0], "comm")
        self.assertEqual(env.calls[-1][2], 2)
        target = env.calls[-1][1]
        self.assertNotIn(target, controller.response_estimates)
        self.assertEqual(controller.p11_selected_prompt_observations[target], 7.5)
        self.assertEqual(controller.p11_selected_prompt_prior, 11.25)

    def test_selected_nondefault_history_never_pollutes_p9_fallback(self):
        env, controller = self.controller((-5.0, 15.0, 10.0))
        self.drive_calibration(env, controller)
        controller.step()
        selected_target = env.calls[-1][1]
        self.assertNotIn(selected_target, controller.response_estimates)
        with patch.object(controller, "_refresh_learned_candidates",
                          side_effect=ValueError("forced")):
            controller._refresh_candidates(env.get_remaining_budget(), "test")
        self.assertTrue(controller.p11_fallback_to_p9)
        self.assertNotIn(selected_target, controller.response_estimates)
        self.assertTrue(all(node_id in controller.p11_probe_nodes
                            for node_id in controller.response_estimates))

    def test_default_constructor_uses_conservative_p9_fallback(self):
        env = PromptEnvironment((-5.0, 15.0, 10.0))
        controller = PromptLearningRuntimeController(
            env, valid_first, node_count=3,
            config=PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=20),
        )
        self.assertEqual(controller.p8_mode, "conservative")

    def test_invalid_llm_output_still_uses_legal_probe_fallback(self):
        env, controller = self.controller((-5.0, 15.0, 10.0), ranker=lambda _: {"bad": True})
        self.drive_calibration(env, controller)
        self.assertEqual(controller.p11_selected_prompt_id, 2)
        self.assertEqual(controller.p11_probe_successes, 3)
        self.assertGreaterEqual(controller.llm_fallbacks, 3)

    def test_harmful_default_tie_selects_nonharmful_prompt(self):
        env, controller = self.controller((-5.0, 15.0, 15.0))
        self.drive_calibration(env, controller)
        self.assertEqual(controller.p11_prompt_ledger.provisional_prompt_ids, (2, 3))
        self.assertEqual(controller.p11_selected_prompt_id, 2)
        self.assertEqual(controller.p11_probe_budget, 6.0)

    def test_equal_nonzero_stops_once_but_all_zero_uses_second_node(self):
        for value in (3.0, -3.0):
            with self.subTest(value=value):
                env, controller = self.controller((value, value, value))
                self.drive_calibration(env, controller)
                self.assertEqual(controller.p11_selected_prompt_id, 1)
                self.assertEqual(controller.p11_selected_prompt_prior, value)
                self.assertEqual(controller.p11_probe_budget, 6.0)

        env, controller = self.controller(
            (-5.0, 15.0, 10.0), factors=(0.0, 1.0, 0.6),
        )
        self.drive_calibration(env, controller)
        self.assertEqual(controller.p11_probe_budget, 12.0)
        self.assertEqual(controller.p11_selected_prompt_id, 2)
        self.assertEqual(controller.p11_selected_prompt_prior, 7.5)
        self.assertFalse(controller.p11_prompt_ledger.confident)

    def test_all_negative_best_generates_no_communication(self):
        env, controller = self.controller((-5.0, -2.0, -4.0))
        self.drive_calibration(env, controller)
        self.assertEqual(controller.p11_selected_prompt_id, 2)
        self.assertEqual(controller.p11_selected_prompt_prior, -2.0)
        self.assertFalse(controller.p11_prompt_positive)
        controller._refresh_candidates(env.get_remaining_budget(), "test")
        self.assertFalse(any(candidate.action.kind == "comm"
                             for candidate in controller.candidates.values()))

    def test_failed_probe_moves_to_second_node_with_bounded_cost(self):
        env, controller = self.controller((-5.0, 15.0, 10.0), fail=(1, 1))
        self.drive_calibration(env, controller)
        self.assertEqual(controller.p11_probe_attempts, 4)
        self.assertEqual(controller.p11_probe_failures, 1)
        self.assertEqual(controller.p11_probe_successes, 3)
        self.assertEqual(controller.p11_probe_budget, 6.0)
        self.assertEqual(controller.p11_selected_prompt_id, 2)


if __name__ == "__main__":
    unittest.main()

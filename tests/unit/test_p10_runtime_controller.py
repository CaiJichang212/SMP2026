"""Execution contract for the development-only P10 runtime controller."""

import unittest
from unittest.mock import patch

from starnet.policy.actions import Action
from starnet.policy.candidates import Candidate
from starnet.policy.config import PolicyConfig, PolicyMode
from starnet.policy.p10_structure_plan_experiment import FullPlanDecision, FullStructurePlan
from starnet.policy.public_response_mixture import PublicResponseMixtureLedger
from starnet.runtime.controller import ControllerState
from starnet.runtime.env_adapter import apply_action_outcome
from starnet.runtime.p10_controller_experiment import P10RuntimeController


class PrefixEnvironment:
    def __init__(self, *, reject_second=False):
        self.budget = 30.0
        self.reject_second = reject_second
        self.calls = []
        self.nodes = {
            1: {"w": -20.0, "persona": "暴力", "comm_left": 3, "neighbors": [2]},
            2: {"w": -10.0, "persona": "暴力", "comm_left": 3, "neighbors": [1, 3]},
            3: {"w": 10.0, "persona": "和平", "comm_left": 3, "neighbors": [2]},
        }
        self.edges = {(1, 2), (2, 3)}

    def get_remaining_budget(self):
        return self.budget

    def scan_node(self, node_id):
        self.calls.append(("scan", node_id))
        self.budget -= 0.5
        return dict(self.nodes[node_id])

    def communicate(self, node_id, prompt_id):
        self.calls.append(("comm", node_id, prompt_id))
        self.budget -= 2.0
        self.nodes[node_id]["comm_left"] -= 1
        self.nodes[node_id]["w"] += 5.0
        return {"status": "success", "new_w": self.nodes[node_id]["w"]}

    def cut_link(self, left, right):
        self.calls.append(("cut", left, right))
        self.budget -= 3.0
        edge = tuple(sorted((left, right)))
        if edge not in self.edges:
            return False
        self.edges.remove(edge)
        return True

    def shield_node(self, node_id):
        self.calls.append(("shield", node_id))
        self.budget -= 5.0
        if self.reject_second and node_id == 2:
            return False
        if node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        self.edges = {edge for edge in self.edges if node_id not in edge}
        return True


def plan_fixture():
    structures = (Action("shield", 1), Action("shield", 2))
    plan = FullStructurePlan(structures, (Action("comm", 3, prompt_id=1),),
                             120.0, 100.0, 5, 20, 0.01)
    decision = FullPlanDecision(
        structures, Action("comm", 3, prompt_id=1), plan,
        (8.0, 7.0, 6.0, -2.0, 5.0),
        (4.0, 3.0, -1.0, 2.0, 5.0, 6.0, 1.0, 2.0),
        True, 26,
    )
    return plan, decision


class P10RuntimeControllerTests(unittest.TestCase):
    def controller(self, ranker, *, reject_second=False):
        env = PrefixEnvironment(reject_second=reject_second)
        controller = P10RuntimeController(
            env, ranker, node_count=3, p8_mode="conservative",
            config=PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=10),
        )
        for node_id in (1, 2, 3):
            apply_action_outcome(env, controller.blackboard, Action("scan", node_id),
                                 env.get_remaining_budget())
        controller.state = ControllerState.ANALYZE
        return env, controller

    @staticmethod
    def baseline_refresh(controller, budget, phase):
        controller.effective_policy_mode = PolicyMode.PUBLIC_GREEDY
        controller.analysis = controller.analyst.analyze(controller.blackboard)
        action = Action("comm", 3, prompt_id=1)
        baseline = Candidate("baseline", action, 0, 1.0, 0.5, "P9", ("baseline",))
        controller.candidates = {baseline.candidate_id: baseline}
        controller.p8_options = False

    def patches(self):
        plan, decision = plan_fixture()
        return plan, decision, (
            patch("starnet.runtime.p10_controller_experiment.P8RuntimeController._refresh_candidates",
                  self.baseline_refresh),
            patch("starnet.runtime.p10_controller_experiment.search_full_structure_plan",
                  return_value=plan),
            patch("starnet.runtime.p10_controller_experiment.choose_full_plan",
                  return_value=decision),
        )

    def test_llm_approval_executes_prefix_one_action_per_step_then_p9(self):
        payloads = []

        def approve(payload):
            payloads.append(payload)
            item = next((candidate for candidate in payload["candidates"]
                         if candidate["candidate_id"].startswith("p10-plan:")),
                        payload["candidates"][0])
            return {"state_version": payload["state_version"], "mode": "single_action",
                    "candidate_id": item["candidate_id"], "reason_code": "approve_prefix",
                    "evidence_ids": [item["evidence_ids"][0]]}

        env, controller = self.controller(approve)
        _, _, patches = self.patches()
        with patches[0], patches[1] as search, patches[2]:
            calls = []
            for _ in range(3):
                before = len(env.calls)
                controller.step()
                calls.append(len(env.calls) - before)
        self.assertEqual(calls, [1, 1, 1])
        self.assertEqual(env.calls[3:6], [("shield", 1), ("shield", 2), ("comm", 3, 1)])
        self.assertEqual(search.call_count, 1)
        self.assertEqual(controller.p10_approved_plans, 1)
        self.assertEqual(controller.p10_prefix_successes, 2)
        self.assertEqual(controller.p10_prefix_completed, 1)
        self.assertEqual(controller.p10_prefix_failures, 0)
        plan_payload = next(payload for payload in payloads
                            if any(item["candidate_id"].startswith("p10-plan:")
                                   for item in payload["candidates"]))
        reason = next(item["reason"] for item in plan_payload["candidates"]
                      if item["candidate_id"].startswith("p10-plan:"))
        self.assertIn("selecting this candidate ID authorizes every", reason)
        self.assertIn("minimum=-2.000000", reason)

    def test_llm_baseline_choice_never_starts_prefix(self):
        def reject(payload):
            item = next((candidate for candidate in payload["candidates"]
                         if not candidate["candidate_id"].startswith("p10-plan:")),
                        payload["candidates"][0])
            return {"state_version": payload["state_version"], "mode": "single_action",
                    "candidate_id": item["candidate_id"], "reason_code": "reject_prefix",
                    "evidence_ids": [item["evidence_ids"][0]]}

        env, controller = self.controller(reject)
        _, _, patches = self.patches()
        with patches[0], patches[1], patches[2]:
            before = len(env.calls)
            controller.step()
        self.assertEqual(len(env.calls) - before, 1)
        self.assertEqual(env.calls[-1], ("comm", 3, 1))
        self.assertEqual(controller.p10_baseline_choices, 1)
        self.assertEqual(controller.p10_approved_plans, 0)
        self.assertEqual(controller.p10_pending, [])

    def test_invalid_llm_output_falls_back_to_p9_not_plan_candidate(self):
        env, controller = self.controller(lambda payload: {"candidate_id": "invalid"})
        _, _, patches = self.patches()
        with patches[0], patches[1], patches[2]:
            controller.step()
        self.assertEqual(env.calls[-1], ("comm", 3, 1))
        self.assertEqual(controller.llm_fallbacks, 1)
        self.assertEqual(controller.p10_baseline_choices, 1)
        self.assertEqual(controller.p10_pending, [])

    def test_p10_preserves_p8_proposal_and_pg_reference_candidates(self):
        def choose_p8(payload):
            item = next(candidate for candidate in payload["candidates"]
                        if candidate["candidate_id"].startswith("p8:"))
            return {"state_version": payload["state_version"], "mode": "single_action",
                    "candidate_id": item["candidate_id"], "reason_code": "choose_p8",
                    "evidence_ids": [item["evidence_ids"][0]]}

        def p8_refresh(controller, budget, phase):
            controller.effective_policy_mode = PolicyMode.PUBLIC_GREEDY
            controller.analysis = controller.analyst.analyze(controller.blackboard)
            proposal = Candidate("p8:proposal", Action("shield", 1), 0, 3.0, 0.6,
                                 "P8 PG-reference gain", ("p8:proposal",))
            reference = Candidate("pg:reference", Action("comm", 3, prompt_id=1),
                                  0, 0.0, 0.0, "PG=0", ("pg:reference",))
            controller.candidates = {proposal.candidate_id: proposal,
                                     reference.candidate_id: reference}
            controller.p8_options = True

        env, controller = self.controller(choose_p8)
        plan, decision = plan_fixture()
        with patch("starnet.runtime.p10_controller_experiment.P8RuntimeController._refresh_candidates",
                   p8_refresh), \
             patch("starnet.runtime.p10_controller_experiment.search_full_structure_plan",
                   return_value=plan), \
             patch("starnet.runtime.p10_controller_experiment.choose_full_plan",
                   return_value=decision):
            controller._refresh_candidates(env.get_remaining_budget(), "test")
            self.assertEqual(len(controller.candidates), 3)
            self.assertIn("p8:proposal", controller.candidates)
            self.assertIn("pg:reference", controller.candidates)
            self.assertAlmostEqual(
                controller.candidates["p8:proposal"].roi,
                controller.candidates["p8:proposal"].score / env.get_remaining_budget(),
            )
            self.assertEqual(controller.candidates["pg:reference"].score, 0.0)
            self.assertIn("PG REFERENCE", controller.candidates["pg:reference"].reason)
            controller._create_plan(env.get_remaining_budget())
        self.assertEqual(controller.queue, ["p8:proposal"])
        self.assertEqual(controller.p10_pending, [])
        self.assertEqual(controller.p8_selected_proposals, 1)

    def test_invalid_llm_uses_original_p8_fallback_even_when_p10_scores_higher(self):
        def p8_refresh(controller, budget, phase):
            controller.effective_policy_mode = PolicyMode.PUBLIC_GREEDY
            controller.analysis = controller.analyst.analyze(controller.blackboard)
            proposal = Candidate("p8:proposal", Action("shield", 1), 0, 3.0, 0.6,
                                 "P8", ("p8:proposal",))
            reference = Candidate("pg:reference", Action("comm", 3, prompt_id=1),
                                  0, 0.0, 0.0, "PG", ("pg:reference",))
            controller.candidates = {proposal.candidate_id: proposal,
                                     reference.candidate_id: reference}
            controller.p8_options = True

        env, controller = self.controller(lambda payload: {"candidate_id": "invalid"})
        plan, decision = plan_fixture()
        with patch("starnet.runtime.p10_controller_experiment.P8RuntimeController._refresh_candidates",
                   p8_refresh), \
             patch("starnet.runtime.p10_controller_experiment.search_full_structure_plan",
                   return_value=plan), \
             patch("starnet.runtime.p10_controller_experiment.choose_full_plan",
                   return_value=decision):
            controller._refresh_candidates(env.get_remaining_budget(), "test")
            controller._create_plan(env.get_remaining_budget())
        self.assertEqual(controller.queue, ["p8:proposal"])
        self.assertNotIn(controller.p10_plan_id, controller.queue)
        self.assertEqual(controller.p10_pending, [])

    def test_combined_initial_plan_uses_original_p9_estimator_before_gate(self):
        env, controller = self.controller(None)
        controller.p10_experiment_mode = "combined"
        controller.p10_response_estimator = PublicResponseMixtureLedger()
        with patch("starnet.runtime.p10_controller_experiment.P8RuntimeController._refresh_candidates",
                   self.baseline_refresh), \
             patch("starnet.runtime.p10_controller_experiment.search_full_structure_plan",
                   return_value=None) as search:
            controller._refresh_candidates(env.get_remaining_budget(), "test")
        self.assertEqual(search.call_count, 1)
        self.assertIsNone(search.call_args.kwargs["response_estimator"])

    def test_failed_middle_action_clears_prefix_after_debited_step(self):
        def approve(payload):
            item = next((candidate for candidate in payload["candidates"]
                         if candidate["candidate_id"].startswith("p10-plan:")),
                        payload["candidates"][0])
            return {"state_version": payload["state_version"], "mode": "single_action",
                    "candidate_id": item["candidate_id"], "reason_code": "approve_prefix",
                    "evidence_ids": [item["evidence_ids"][0]]}

        env, controller = self.controller(approve, reject_second=True)
        _, _, patches = self.patches()
        with patches[0], patches[1], patches[2]:
            budgets = []
            for _ in range(3):
                before_calls = len(env.calls)
                controller.step()
                self.assertLessEqual(len(env.calls) - before_calls, 1)
                budgets.append(env.budget)
        self.assertEqual(env.calls[3:6], [("shield", 1), ("shield", 2), ("comm", 3, 1)])
        self.assertEqual(budgets, [23.5, 18.5, 16.5])
        self.assertEqual(controller.p10_pending, [])
        self.assertEqual(controller.p10_prefix_successes, 1)
        self.assertEqual(controller.p10_prefix_failures, 1)
        self.assertEqual(controller.action_failures, 1)

    def test_optional_response_hook_observes_only_successful_first_returns(self):
        class Ledger:
            def __init__(self):
                self.observed = []

            def gate_open(self):
                return True

            def predict(self, node_id, persona, turn, observed, *, gated):
                return 12.75 * (0.5 ** (turn - 1))

            def observe_first(self, persona, before, new_w):
                self.observed.append((persona, before, new_w))

        ledger = Ledger()
        env = PrefixEnvironment()
        controller = P10RuntimeController(
            env, None, node_count=3, p8_mode="conservative", response_estimator=ledger,
            experiment_mode="combined",
            config=PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=0),
        )
        for node_id in (1, 2, 3):
            apply_action_outcome(env, controller.blackboard, Action("scan", node_id),
                                 env.get_remaining_budget())
        self.assertIsNotNone(controller._p10_response_fn())
        controller._attempt_action(Action("comm", 3, prompt_id=1), "test", env.get_remaining_budget())
        controller._attempt_action(Action("comm", 3, prompt_id=1), "test", env.get_remaining_budget())
        self.assertEqual(ledger.observed, [("和平", 10.0, 15.0)])

    def test_response_gate_pauses_p8_and_response_only_never_searches_plan(self):
        class Ledger:
            def gate_open(self):
                return True

            def predict(self, node_id, persona, turn, observed, *, gated):
                return 12.75 * (0.5 ** (turn - 1))

            def observe_first(self, persona, before, new_w):
                return True

        env, controller = self.controller(None)
        controller.p10_experiment_mode = "response_only"
        controller.p10_response_estimator = Ledger()
        response = Candidate("response", Action("comm", 3, prompt_id=1),
                             0, 5.0, 2.5, "gated", ("response",))
        with patch("starnet.runtime.p10_controller_experiment.P8RuntimeController._refresh_candidates",
                   side_effect=AssertionError("P8 must be paused")), \
             patch("starnet.runtime.p10_controller_experiment.ExperimentalPublicGreedyPlanner.candidates",
                   return_value=[response]), \
             patch("starnet.runtime.p10_controller_experiment.search_full_structure_plan") as search:
            controller._refresh_candidates(env.get_remaining_budget(), "test")
        self.assertEqual(controller.candidates, {"response": response})
        self.assertEqual(controller.p10_response_switches, 1)
        self.assertEqual(controller.p10_searches, 0)
        search.assert_not_called()

    def test_response_prediction_error_disables_estimator_and_keeps_p9_candidates(self):
        class BrokenLedger:
            def gate_open(self):
                return True

            def predict(self, *args, **kwargs):
                raise TimeoutError

        env, controller = self.controller(None)
        controller.p10_experiment_mode = "response_only"
        controller.p10_response_estimator = BrokenLedger()
        with patch("starnet.runtime.p10_controller_experiment.P8RuntimeController._refresh_candidates",
                   self.baseline_refresh):
            controller._refresh_candidates(env.get_remaining_budget(), "test")
        self.assertTrue(controller.p10_response_disabled)
        self.assertEqual(controller.p10_response_disable_reason, "TimeoutError")
        self.assertEqual(set(controller.candidates), {"baseline"})

    def test_stage_envelope_that_disables_p8_also_disables_both_p10_paths(self):
        env = PrefixEnvironment()
        controller = P10RuntimeController(
            env, None, node_count=3, p8_mode="conservative",
            require_stage_envelope=True, experiment_mode="combined",
            config=PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=0),
        )
        for node_id in (1, 2, 3):
            apply_action_outcome(env, controller.blackboard, Action("scan", node_id),
                                 env.get_remaining_budget())
        with patch("starnet.runtime.p10_controller_experiment.search_full_structure_plan") as search:
            controller._refresh_candidates(env.get_remaining_budget(), "test")
        search.assert_not_called()
        self.assertIsNone(controller.p8_mode)
        self.assertEqual(controller.p10_searches, 0)
        self.assertEqual(controller.p10_response_switches, 0)

    def test_observe_error_disables_estimator_after_public_fact_is_recorded(self):
        class BrokenObserve:
            def gate_open(self):
                return False

            def predict(self, *args, **kwargs):
                return 12.75

            def observe_first(self, *args):
                raise RuntimeError

        env = PrefixEnvironment()
        controller = P10RuntimeController(
            env, None, node_count=3, p8_mode="conservative",
            experiment_mode="response_only", response_estimator=BrokenObserve(),
            config=PolicyConfig(policy_mode=PolicyMode.PUBLIC_GREEDY, max_llm_calls=0),
        )
        for node_id in (1, 2, 3):
            apply_action_outcome(env, controller.blackboard, Action("scan", node_id),
                                 env.get_remaining_budget())
        controller._attempt_action(Action("comm", 3, prompt_id=1), "test",
                                   env.get_remaining_budget())
        self.assertEqual(controller.blackboard.nodes[3].w, 15.0)
        self.assertEqual(controller.blackboard.nodes[3].comm_left, 2)
        self.assertTrue(controller.p10_response_disabled)
        self.assertEqual(controller.p10_response_disable_reason, "RuntimeError")


if __name__ == "__main__":
    unittest.main()

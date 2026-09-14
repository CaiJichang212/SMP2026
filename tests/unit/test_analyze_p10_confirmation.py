"""Strict evidence and statistical gates for P10 confirmation."""

from __future__ import annotations

import copy
import itertools
import unittest

from scripts.analyze_p10_confirmation import (
    FAMILIES, PRIMARY, STRATA, audit_candidate_runtime, audit_episode,
    block_bootstrap, json_digest, statistical_gate,
)
from scripts.run_p9_distribution_validation import LoggedEnvironment
from starnet.experiments.p10_confirmation_seeds import seed_payload
from starnet.policy.public_response_mixture import PublicResponseMixtureLedger


class P10ConfirmationAnalysisTests(unittest.TestCase):
    def episode(self):
        seed = seed_payload("er_resampled", 1201, "independent", allow_confirmation=True)
        env = LoggedEnvironment(seed)
        for node_id in range(1, 51):
            env.scan_node(node_id)
        env.communicate(1, 1)
        records = env.action_log
        result = {
            "score": env.evaluate(), "remaining_budget": env.get_remaining_budget(),
            "host_calls": len(records), "host_action_deltas": [1] * len(records),
            "host_steps": [{"host_call": index, "action_delta": 1, "action": record}
                           for index, record in enumerate(records, 1)],
            "max_actions_per_host_step": 1, "one_action_per_host_step": True,
            "action_attempts": len(records), "action_failures": 0,
            "action_log_sha256": json_digest(records), "action_log": records,
            "llm_calls": 0, "llm_accepted": 0, "llm_fallbacks": 0,
            "p8_planning_errors": 0, "p10_planning_errors": 0,
            "p10_prefix_failures": 0, "p10_response_disabled": False,
        }
        return seed, result

    def test_public_history_replay_checks_step_budget_clip_and_score(self):
        seed, result = self.episode()
        ledger = audit_episode(result, seed)
        self.assertEqual(len(ledger.accepted), 1)
        invalid = copy.deepcopy(result)
        invalid["host_action_deltas"][0] = 2
        with self.assertRaisesRegex(ValueError, "one-action"):
            audit_episode(invalid, seed)
        invalid = copy.deepcopy(result)
        invalid["action_log"][-1]["public_result"]["new_w"] += 1.0
        invalid["action_log_sha256"] = json_digest(invalid["action_log"])
        with self.assertRaisesRegex(ValueError, "clipped"):
            audit_episode(invalid, seed)
        invalid = copy.deepcopy(result)
        invalid["score"] += 1.0
        with self.assertRaisesRegex(ValueError, "terminal"):
            audit_episode(invalid, seed)

    def test_approved_plan_id_must_match_exact_executed_prefix(self):
        ledger = PublicResponseMixtureLedger()
        prefix = [
            {"kind": "shield", "target_node_1": 1,
             "target_node_2": None, "prompt_id": None},
            {"kind": "cut", "target_node_1": 2,
             "target_node_2": 3, "prompt_id": None},
        ]
        scans = [{"kind": "scan", "target_node_1": node,
                  "target_node_2": None, "prompt_id": None}
                 for node in range(1, 51)]
        actions = scans + prefix
        result = {
            "variant": "combined", "p10_experiment_mode": "combined",
            "controller_type": "P10RuntimeController",
            "effective_p8_mode": "conservative",
            "p10_searches": 1, "p10_search_completed": True,
            "p10_pending_count": 0, "p10_last_planning_error": None,
            "p8_last_planning_error": None, "p10_plan_id": "p10-plan:x",
            "p10_plan": {"structure_actions": prefix},
            "p10_plan_decision": {"accepted": True},
            "p10_approved_plans": 1, "p10_prefix_completed": 1,
            "p10_prefix_successes": 2,
            "action_log": actions,
            "model_decisions": [{
                "selected_candidate_id": "p10-plan:x",
                "candidate_ids": ["p10-plan:x", "pg"],
                "candidate_scores": {"p10-plan:x": 10.0, "pg": 0.0},
                "candidate_rois": {"p10-plan:x": 10.0 / 75.0, "pg": 0.0},
                "candidate_reasons": {"p10-plan:x": "P10 COMPLETE", "pg": "PG REFERENCE: zero"},
                "budget": 75.0, "mode": "single_action",
            }],
            "p10_response_activation": None,
            "p10_response_final_weights": ledger.weights(),
            "p10_response_accepted": [],
            "p10_response_censored": [],
            "p10_response_switches": 0,
        }
        audit_candidate_runtime(result, ledger)
        invalid = copy.deepcopy(result)
        invalid["action_log"] = copy.deepcopy(invalid["action_log"])
        invalid["action_log"][51]["target_node_2"] = 4
        with self.assertRaisesRegex(ValueError, "prefix"):
            audit_candidate_runtime(invalid, ledger)

    def rows(self, value=1.0):
        return [{
            "family": family, "repetition": repetition, "stratum": stratum,
            "paired_deltas": {PRIMARY: float(value)},
        } for family, repetition, stratum in itertools.product(
            FAMILIES, (1201, 1202, 1203), STRATA,
        )]

    def test_block_bootstrap_keeps_all_strata_in_repetition_block(self):
        rows = self.rows(0.0)
        for row in rows:
            row["paired_deltas"][PRIMARY] = 8.0 if row["stratum"] == STRATA[0] else (
                -8.0 if row["stratum"] == STRATA[1] else 0.0
            )
        self.assertEqual(block_bootstrap(rows, PRIMARY, draws=1000), [0.0, 0.0])

    def test_statistical_gate_requires_ci_strata_and_two_positive_families(self):
        rows = self.rows(2.0)
        passed, _, ci, _, _, positive = statistical_gate(rows)
        self.assertTrue(passed)
        self.assertGreater(ci[0], 0.0)
        self.assertEqual(positive, 4)

        one_family = self.rows(0.0)
        for row in one_family:
            if row["family"] == FAMILIES[0]:
                row["paired_deltas"][PRIMARY] = 4.0
        self.assertFalse(statistical_gate(one_family)[0])

        bad_stratum = self.rows(2.0)
        for row in bad_stratum:
            if row["stratum"] == STRATA[0]:
                row["paired_deltas"][PRIMARY] = -1.0
        self.assertFalse(statistical_gate(bad_stratum)[0])


if __name__ == "__main__":
    unittest.main()

import copy
import itertools
import json
import unittest

from scripts.analyze_p9_bounded_release import (
    FAMILIES, MECHANISM_REPORT, MECHANISM_SOURCE, PRIMARY, SHIFT_STRATA,
    audit_episode, audit_mechanism_report, audit_uncapped_envelope,
    block_bootstrap, digest, json_digest,
)
from scripts.run_p9_distribution_validation import LoggedEnvironment
from starnet.experiments.p9_distribution_seeds import seed_payload


class BoundedReleaseAuditTests(unittest.TestCase):
    def episode(self):
        seed = {"global_setting": {"max_budget": 100}, "edges": [],
                "nodes": [{"id": node, "w": 99.0, "persona": "和平", "r": 1.5, "comm_left": 3}
                          for node in range(1, 51)]}
        env = LoggedEnvironment(seed)
        for node in range(1, 51):
            env.scan_node(node)
        env.communicate(1, 1)
        env.communicate(1, 1)
        return {"action_log": env.action_log, "action_attempts": 52,
                "action_failures": 0, "remaining_budget": env.get_remaining_budget(),
                "score": env.evaluate()}

    def test_counts_wasted_budget_separately_from_successful_api_calls(self):
        self.assertEqual(audit_episode(self.episode()), 1)

    def test_rejects_unaccounted_budget_and_unbounded_public_return(self):
        episode = self.episode()
        invalid = copy.deepcopy(episode)
        invalid["action_log"][-1]["budget_after"] += 2
        with self.assertRaises(ValueError):
            audit_episode(invalid)
        invalid = copy.deepcopy(episode)
        invalid["action_log"][-1]["public_result"]["new_w"] = 101
        with self.assertRaises(ValueError):
            audit_episode(invalid)

    def test_seed_bound_episode_audit_rejects_changed_public_fact_and_log_hash(self):
        seed = seed_payload("er_resampled", 901, "centered_independent")
        env = LoggedEnvironment(seed)
        for node in range(1, 51):
            env.scan_node(node)
        env.communicate(1, 1)
        result = {
            "action_log": env.action_log,
            "action_log_sha256": json_digest(env.action_log),
            "action_attempts": len(env.action_log),
            "action_counts": {"scan": 50, "comm": 1, "cut": 0, "shield": 0},
            "action_failures": 0,
            "remaining_budget": env.get_remaining_budget(),
            "score": env.evaluate(),
        }
        self.assertEqual(audit_episode(result, seed), 0)
        invalid = copy.deepcopy(result)
        invalid["action_log"][0]["public_result"]["w"] += 1.0
        invalid["action_log_sha256"] = json_digest(invalid["action_log"])
        with self.assertRaisesRegex(ValueError, "scan facts"):
            audit_episode(invalid, seed)
        invalid = copy.deepcopy(result)
        invalid["action_log_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "action count"):
            audit_episode(invalid, seed)
        invalid = copy.deepcopy(result)
        invalid["action_log"][-1]["public_result"]["new_w"] += 0.5
        invalid["action_log_sha256"] = json_digest(invalid["action_log"])
        with self.assertRaisesRegex(ValueError, "paired seed"):
            audit_episode(invalid, seed)

    def test_mechanism_gate_requires_all_108_chained_observations(self):
        report = json.loads(MECHANISM_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(
            audit_mechanism_report(report, source_sha256=digest(MECHANISM_SOURCE)), 108,
        )
        invalid = copy.deepcopy(report)
        invalid["runs"][0]["observations"].pop()
        with self.assertRaisesRegex(ValueError, "complete nine-node"):
            audit_mechanism_report(invalid, source_sha256=digest(MECHANISM_SOURCE))

    def test_uncapped_envelope_is_proved_from_seed_values(self):
        for family, repetition, shift in itertools.product(
            FAMILIES, (901, 902), SHIFT_STRATA[:-2],
        ):
            self.assertTrue(audit_uncapped_envelope(seed_payload(family, repetition, shift)))
        boundary = seed_payload("er_resampled", 901, "centered_independent")
        boundary["nodes"][0]["w"] = 99.0
        boundary["nodes"][0]["r"] = 1.5
        with self.assertRaisesRegex(ValueError, "opinion bound"):
            audit_uncapped_envelope(boundary)

    def test_resamples_whole_graphs_not_individual_shifts(self):
        repetitions = (1001, 1002, 1003)
        # Opposing shifts on the same graph cancel exactly. Treating them
        # as independent observations would invent uncertainty here.
        effects = (7.0, -7.0, 0., 0., 0., 0., 0.)
        rows = [{"family": family, "repetition": repetition, "shift_stratum": shift,
                 "paired_deltas": {PRIMARY: effect * (repetition - 1000)}}
                for family, repetition in itertools.product(FAMILIES, repetitions)
                for shift, effect in zip(SHIFT_STRATA, effects)]
        self.assertEqual(block_bootstrap(rows, PRIMARY, repetitions, 1000), [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()

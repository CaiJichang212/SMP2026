import copy
import itertools
import unittest

from scripts.analyze_p9_bounded_release import (
    FAMILIES, PRIMARY, SHIFT_STRATA, audit_episode, block_bootstrap,
)
from scripts.run_p9_distribution_validation import LoggedEnvironment


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

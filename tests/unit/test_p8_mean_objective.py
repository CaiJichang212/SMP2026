import unittest

from scripts.analyze_p8_mean_objective import paired_summary, stressed_gain


class MeanObjectiveTests(unittest.TestCase):
    def test_weight_constraint_solution_matches_small_enumeration(self):
        values = [-1.0, 3.0]
        feasible = [weight * values[0] + (1 - weight) * values[1]
                    for weight in (.25, .5, .75)]
        self.assertEqual(stressed_gain(values), min(feasible))
        self.assertEqual(stressed_gain([1.0, 1.0, 1.0]), 1.0)

    def test_fixed_family_bootstrap_does_not_change_stratum_weights(self):
        result = paired_summary({"negative": [-1.0] * 5, "positive": [9.0] * 5}, samples=200)
        self.assertEqual(result["stratified_bootstrap_95_interval"], [4.0, 4.0])
        self.assertEqual(result["composition_stress_bootstrap_95_interval"], [1.5, 1.5])
        self.assertTrue(result["mean_score_statistical_gate_passed"])

    def test_zero_or_negative_stressed_gain_is_not_promoted(self):
        self.assertFalse(paired_summary({"a": [0.0] * 5}, samples=200)["mean_score_statistical_gate_passed"])
        self.assertFalse(paired_summary({"a": [-3.0] * 5, "b": [4.0] * 5}, samples=200)["mean_score_statistical_gate_passed"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from starnet.policy.public_response_mixture import PublicResponseMixtureLedger


class OnlineResponseMixtureTests(unittest.TestCase):
    def test_initial_prediction_matches_fixed_prior_for_every_persona(self) -> None:
        mixture = PublicResponseMixtureLedger()
        for persona in ("和平", "中立", "暴力"):
            self.assertAlmostEqual(mixture.predict_first(persona), 12.75)

    def test_aligned_public_observations_update_without_zeroing_inverse(self) -> None:
        mixture = PublicResponseMixtureLedger()
        self.assertTrue(mixture.observe_first("和平", 0.0, 18.0))
        weights = mixture.weights()
        self.assertGreater(weights["aligned"], weights["inverse"])
        self.assertGreater(weights["inverse"], 0.0)

    def test_bound_response_is_censored(self) -> None:
        mixture = PublicResponseMixtureLedger()
        before = mixture.weights()
        self.assertFalse(mixture.observe_first("和平", 99.0, 100.0))
        self.assertEqual(mixture.weights(), before)
        self.assertEqual(mixture.censored[0]["reason"], "opinion_bound")

    def test_gated_prediction_waits_for_four_high_confidence_observations(self) -> None:
        mixture = PublicResponseMixtureLedger()
        for count in range(1, 5):
            mixture.observe_first("和平", 0.0, 18.0)
            if count < 4:
                self.assertFalse(mixture.gate_open())
                self.assertEqual(mixture.predict_gated_first("和平"), 12.75)
        self.assertTrue(mixture.gate_open())
        self.assertGreater(mixture.predict_gated_first("和平"), 12.75)
        self.assertEqual(mixture.activation["accepted_observation_count"], 4)


if __name__ == "__main__":
    unittest.main()

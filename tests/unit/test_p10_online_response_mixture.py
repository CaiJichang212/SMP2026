from __future__ import annotations

import math
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

    def test_unknown_persona_falls_back_or_uses_own_observation(self) -> None:
        mixture = PublicResponseMixtureLedger()
        self.assertEqual(mixture.predict_first("unknown"), 12.75)
        self.assertEqual(mixture.predict(1, "unknown", 1, {}, gated=False), 12.75)
        self.assertEqual(mixture.predict(1, "unknown", 2, {1: 8.0}, gated=False), 4.0)

    def test_invalid_observations_do_not_raise_or_change_weights(self) -> None:
        mixture = PublicResponseMixtureLedger()
        before = mixture.weights()
        for persona, old_w, new_w in (
            ("unknown", 0.0, 12.0),
            ("和平", "invalid", 12.0),
            ("和平", 0.0, None),
            ("和平", math.nan, 12.0),
            ("和平", 0.0, math.inf),
        ):
            self.assertFalse(mixture.observe_first(persona, old_w, new_w))
            self.assertEqual(mixture.weights(), before)
        self.assertEqual(len(mixture.accepted), 0)

    def test_registered_density_boundaries_tolerate_float_subtraction(self) -> None:
        for response_factor in (0.2 - 1e-12, 0.65 + 1e-12, 1.05 - 1e-12, 1.5 + 1e-12):
            mixture = PublicResponseMixtureLedger()
            self.assertTrue(mixture.observe_first("和平", 10.0, 10.0 + 15.0 * response_factor))
            self.assertEqual(len(mixture.accepted), 1)


if __name__ == "__main__":
    unittest.main()

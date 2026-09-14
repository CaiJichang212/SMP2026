from __future__ import annotations

import unittest

from scripts.run_p10_online_response_mixture import OnlineResponseMixture


class OnlineResponseMixtureTests(unittest.TestCase):
    def test_initial_prediction_matches_fixed_prior_for_every_persona(self) -> None:
        mixture = OnlineResponseMixture()
        for persona in ("和平", "中立", "暴力"):
            self.assertAlmostEqual(mixture.predict_first(persona), 12.75)

    def test_aligned_public_observations_update_without_zeroing_inverse(self) -> None:
        mixture = OnlineResponseMixture()
        self.assertTrue(mixture.observe_first("和平", 0.0, 18.0))
        weights = mixture.weights()
        self.assertGreater(weights["aligned"], weights["inverse"])
        self.assertGreater(weights["inverse"], 0.0)

    def test_bound_response_is_censored(self) -> None:
        mixture = OnlineResponseMixture()
        before = mixture.weights()
        self.assertFalse(mixture.observe_first("和平", 99.0, 100.0))
        self.assertEqual(mixture.weights(), before)
        self.assertEqual(mixture.censored[0]["reason"], "opinion_bound")


if __name__ == "__main__":
    unittest.main()

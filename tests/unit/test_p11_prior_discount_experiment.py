from __future__ import annotations

import unittest

from starnet.runtime.p11_prior_discount_experiment import (
    DiscountedPromptLearningRuntimeController,
)


class P11PriorDiscountTests(unittest.TestCase):
    def test_only_cross_node_empirical_prior_is_discounted(self):
        controller = object.__new__(DiscountedPromptLearningRuntimeController)
        controller.p11_prior_discount = 0.9
        controller.p11_selected_prompt_probe_values = (20.0,)
        controller.p11_selected_prompt_observations = {4: 10.0}
        controller.p11_empirical_prompt_prior = None
        controller.p11_discounted_prompt_prior = None
        controller.p11_selected_prompt_prior = None
        controller.p11_prompt_positive = False
        controller.p11_prior_predictions = 0
        self.assertEqual(controller._current_selected_prompt_prior(), 13.5)
        self.assertEqual(controller.p11_empirical_prompt_prior, 15.0)
        self.assertEqual(controller.p11_discounted_prompt_prior, 13.5)
        # The concrete-node history remains raw and is consumed directly by
        # the base response closure before it falls back to this prior.
        self.assertEqual(controller.p11_selected_prompt_observations[4], 10.0)
        self.assertEqual(controller.p11_prior_predictions, 1)

    def test_discount_configuration_is_bounded(self):
        for value in (0.0, -0.1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                DiscountedPromptLearningRuntimeController.__init__(
                    object.__new__(DiscountedPromptLearningRuntimeController),
                    prior_discount=value,
                )


if __name__ == "__main__":
    unittest.main()

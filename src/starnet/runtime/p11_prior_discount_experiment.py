"""Development-only P11 transfer-prior discount; never part of INLINE."""

from __future__ import annotations

import math
import statistics

from starnet.runtime.p11_prompt_controller_experiment import PromptLearningRuntimeController


class DiscountedPromptLearningRuntimeController(PromptLearningRuntimeController):
    """Discount only the selected-prompt empirical mean for unknown nodes."""

    def __init__(self, *args, prior_discount: float = 0.9, **kwargs):
        if not math.isfinite(prior_discount) or not 0.0 < prior_discount <= 1.0:
            raise ValueError("invalid P11 empirical prior discount")
        super().__init__(*args, **kwargs)
        self.p11_prior_discount = float(prior_discount)
        self.p11_empirical_prompt_prior: float | None = None
        self.p11_discounted_prompt_prior: float | None = None
        self.p11_prior_predictions = 0

    def _current_selected_prompt_prior(self) -> float:
        values = (
            *self.p11_selected_prompt_probe_values,
            *self.p11_selected_prompt_observations.values(),
        )
        if not values:
            raise ValueError("missing selected-prompt public response")
        empirical = statistics.fmean(float(value) for value in values)
        if not math.isfinite(empirical):
            raise ValueError("nonfinite selected-prompt empirical mean")
        predicted = self.p11_prior_discount * empirical
        self.p11_empirical_prompt_prior = empirical
        self.p11_discounted_prompt_prior = predicted
        self.p11_selected_prompt_prior = predicted
        self.p11_prompt_positive = predicted > 0.0
        self.p11_prior_predictions += 1
        return predicted


__all__ = ["DiscountedPromptLearningRuntimeController"]

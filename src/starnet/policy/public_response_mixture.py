"""Pure public-observation response mixture for injectable experiments."""

from __future__ import annotations

import math
from typing import Mapping


MODELS = ("independent", "aligned", "inverse")
INITIAL_WEIGHTS = {"independent": 0.5, "aligned": 0.25, "inverse": 0.25}
FIXED_FIRST_DELTA = 12.75
_DENSITY_BOUND_TOLERANCE = 1e-9
_KNOWN_PERSONAS = {"和平", "中立", "暴力"}


def _response_range(model: str, persona: str) -> tuple[float, float]:
    if persona not in _KNOWN_PERSONAS:
        raise ValueError("unknown public persona")
    if persona == "中立" or model == "independent":
        return 0.2, 1.5
    if model == "aligned":
        return (1.05, 1.5) if persona == "和平" else (0.2, 0.65)
    if model == "inverse":
        return (0.2, 0.65) if persona == "和平" else (1.05, 1.5)
    raise ValueError("unknown response model")


def _density(bounds: tuple[float, float], value: float) -> float:
    low, high = bounds
    return (
        1.0 / (high - low)
        if low - _DENSITY_BOUND_TOLERANCE <= value <= high + _DENSITY_BOUND_TOLERANCE
        else 0.0
    )


class PublicResponseMixtureLedger:
    """Update response hypotheses only from public, uncensored first deltas.

    The ledger has no node identity, so callers must submit at most one first
    observation per node. Adding identity now would change the established
    integration contract; runtime adapters own that deduplication boundary.
    """

    def __init__(self, *, minimum_observations: int = 4,
                 posterior_threshold: float = 0.95) -> None:
        if minimum_observations <= 0 or not 0.0 < posterior_threshold <= 1.0:
            raise ValueError("invalid response-mixture gate")
        self.minimum_observations = minimum_observations
        self.posterior_threshold = posterior_threshold
        self.log_weights = {model: math.log(INITIAL_WEIGHTS[model]) for model in MODELS}
        self.accepted: list[dict[str, object]] = []
        self.censored: list[dict[str, object]] = []
        self.activation: dict[str, object] | None = None

    def weights(self) -> dict[str, float]:
        peak = max(self.log_weights.values())
        raw = {model: math.exp(value - peak) for model, value in self.log_weights.items()}
        total = sum(raw.values())
        return {model: raw[model] / total for model in MODELS}

    def gate_open(self) -> bool:
        weights = self.weights()
        return (
            len(self.accepted) >= self.minimum_observations
            and max(weights["aligned"], weights["inverse"]) >= self.posterior_threshold
        )

    def predict_first(self, persona: str) -> float:
        if persona not in _KNOWN_PERSONAS:
            return FIXED_FIRST_DELTA
        weights = self.weights()
        return 15.0 * sum(
            weights[model] * sum(_response_range(model, persona)) / 2.0
            for model in MODELS
        )

    def predict_gated_first(self, persona: str) -> float:
        return self.predict_first(persona) if self.gate_open() else FIXED_FIRST_DELTA

    def predict(
        self, node_id: int, persona: str, turn: int,
        observed_first: Mapping[int, float], *, gated: bool,
    ) -> float:
        if turn not in (1, 2, 3):
            raise ValueError("invalid communication turn")
        first = observed_first.get(node_id)
        if first is not None:
            try:
                first = float(first)
            except (TypeError, ValueError):
                first = None
            if first is not None and not math.isfinite(first):
                first = None
        if first is None:
            first = self.predict_gated_first(persona) if gated else self.predict_first(persona)
        return max(0.0, float(first)) * (0.5 ** (turn - 1))

    def observe_first(self, persona: str, before: float, new_w: float) -> bool:
        if persona not in _KNOWN_PERSONAS:
            self.censored.append({"reason": "unknown_persona"})
            return False
        try:
            before, new_w = float(before), float(new_w)
        except (TypeError, ValueError):
            self.censored.append({"reason": "nonfinite_or_non_numeric"})
            return False
        if not math.isfinite(before) or not math.isfinite(new_w):
            self.censored.append({"reason": "nonfinite_or_non_numeric"})
            return False
        record: dict[str, object] = {
            "persona": persona, "before": before, "new_w": new_w,
            "delta": new_w - before,
        }
        if before < -100.0 or before > 100.0 or abs(new_w) >= 100.0 - 1e-12:
            record["reason"] = "opinion_bound"
            self.censored.append(record)
            return False
        response_factor = (new_w - before) / 15.0
        independent_density = _density((0.2, 1.5), response_factor)
        if independent_density <= 0.0:
            record["reason"] = "outside_registered_support"
            self.censored.append(record)
            return False
        was_open = self.gate_open()
        for model in MODELS:
            likelihood = (
                0.9 * _density(_response_range(model, persona), response_factor)
                + 0.1 * independent_density
            )
            self.log_weights[model] += math.log(likelihood)
        record["response_factor"] = response_factor
        record["posterior_weights"] = self.weights()
        self.accepted.append(record)
        if not was_open and self.gate_open():
            self.activation = {
                "accepted_observation_count": len(self.accepted),
                "posterior_weights": self.weights(),
            }
        return True


__all__ = ["FIXED_FIRST_DELTA", "PublicResponseMixtureLedger"]

"""Public-only guarded composition over the existing response mixture."""

from __future__ import annotations

import math
from typing import Mapping

from starnet.policy.public_response_mixture import (
    FIXED_FIRST_DELTA,
    PublicResponseMixtureLedger,
)


class GuardedResponseMixtureLedger:
    """Require identity, topology and persona evidence before adaptation."""

    def __init__(self) -> None:
        self._mixture = PublicResponseMixtureLedger(
            minimum_observations=8,
            posterior_threshold=0.99,
        )
        self.accepted = self._mixture.accepted
        self.censored = self._mixture.censored
        self.activation: dict[str, object] | None = None
        self._initial_degrees: dict[int, int] | None = None
        self._seen_nodes: set[int] = set()

    def configure_initial_degrees(self, degrees: Mapping[int, int]) -> bool:
        """Freeze a complete public node-to-initial-degree mapping once."""
        try:
            frozen = {
                node_id: degree
                for node_id, degree in degrees.items()
                if (isinstance(node_id, int) and not isinstance(node_id, bool)
                    and isinstance(degree, int) and not isinstance(degree, bool)
                    and node_id > 0 and degree >= 0)
            }
        except (AttributeError, TypeError, ValueError):
            return False
        if not frozen or len(frozen) != len(degrees):
            return False
        if self._initial_degrees is None:
            self._initial_degrees = dict(frozen)
            return True
        return self._initial_degrees == frozen

    def weights(self) -> dict[str, float]:
        return self._mixture.weights()

    def _degree_correlation(self) -> float | None:
        if self._initial_degrees is None or not self.accepted:
            return None
        degrees = [float(record["initial_degree"]) for record in self.accepted]
        responses = [float(record["response_factor"]) for record in self.accepted]
        degree_mean = sum(degrees) / len(degrees)
        response_mean = sum(responses) / len(responses)
        degree_variance = sum((value - degree_mean) ** 2 for value in degrees)
        if degree_variance <= 0.0:
            return 0.0
        response_variance = sum((value - response_mean) ** 2 for value in responses)
        if response_variance <= 0.0:
            return 0.0
        covariance = sum(
            (degree - degree_mean) * (response - response_mean)
            for degree, response in zip(degrees, responses)
        )
        return covariance / math.sqrt(degree_variance * response_variance)

    def _dominant_model(self) -> str | None:
        weights = self.weights()
        dominant = "aligned" if weights["aligned"] >= weights["inverse"] else "inverse"
        return dominant if weights[dominant] >= 0.99 else None

    def _persona_contrast(self, dominant: str) -> dict[str, object] | None:
        samples = {persona: [] for persona in ("和平", "中立", "暴力")}
        for record in self.accepted:
            samples[str(record["persona"])].append(float(record["response_factor"]))
        means = {
            persona: sum(values) / len(values)
            for persona, values in samples.items() if values
        }
        order = ("和平", "中立", "暴力") if dominant == "aligned" else ("暴力", "中立", "和平")
        for higher_index, higher in enumerate(order):
            for lower in order[higher_index + 1:]:
                if len(samples[higher]) < 2 or len(samples[lower]) < 2:
                    continue
                separation = means[higher] - means[lower]
                if separation >= 0.15:
                    return {
                        "higher_persona": higher,
                        "lower_persona": lower,
                        "higher_count": len(samples[higher]),
                        "lower_count": len(samples[lower]),
                        "separation": separation,
                    }
        return None

    def _guard_evidence(self) -> dict[str, object] | None:
        if self._initial_degrees is None or len(self.accepted) < 8:
            return None
        dominant = self._dominant_model()
        correlation = self._degree_correlation()
        if dominant is None or correlation is None or abs(correlation) >= 0.8:
            return None
        contrast = self._persona_contrast(dominant)
        if contrast is None:
            return None
        return {
            "accepted_observation_count": len(self.accepted),
            "posterior_weights": self.weights(),
            "dominant_model": dominant,
            "degree_response_correlation": correlation,
            "persona_contrast": contrast,
        }

    def gate_open(self) -> bool:
        return self._guard_evidence() is not None

    def predict(
        self, node_id: int, persona: str, turn: int,
        observed_first: Mapping[int, float], *, gated: bool,
    ) -> float:
        if turn not in (1, 2, 3):
            raise ValueError("invalid communication turn")
        observed = observed_first.get(node_id)
        if observed is not None:
            try:
                observed = float(observed)
            except (TypeError, ValueError):
                observed = None
            if observed is not None and math.isfinite(observed):
                return max(0.0, observed) * (0.5 ** (turn - 1))
        first = (
            self._mixture.predict_first(persona)
            if not gated or self.gate_open()
            else FIXED_FIRST_DELTA
        )
        return max(0.0, first) * (0.5 ** (turn - 1))

    def observe_node_first(
        self, node_id: int, persona: str, before: float, new_w: float,
    ) -> bool:
        if not isinstance(node_id, int) or isinstance(node_id, bool) or node_id <= 0:
            self.censored.append({"reason": "invalid_node_id"})
            return False
        degree = self._initial_degrees.get(node_id) if self._initial_degrees is not None else None
        if node_id in self._seen_nodes:
            self.censored.append({"node_id": node_id, "initial_degree": degree,
                                  "reason": "duplicate_node"})
            return False
        self._seen_nodes.add(node_id)
        if degree is None:
            self.censored.append({"node_id": node_id, "initial_degree": None,
                                  "reason": "missing_initial_degree"})
            return False
        accepted_before, censored_before = len(self.accepted), len(self.censored)
        accepted = self._mixture.observe_first(persona, before, new_w)
        # The composed base gate intentionally does not own guarded activation.
        self._mixture.activation = None
        target = (
            self.accepted[-1] if len(self.accepted) > accepted_before
            else self.censored[-1] if len(self.censored) > censored_before
            else None
        )
        if target is not None:
            target["node_id"] = node_id
            target["initial_degree"] = degree
        if accepted and self.activation is None:
            evidence = self._guard_evidence()
            if evidence is not None:
                self.activation = evidence
        return accepted


__all__ = ["GuardedResponseMixtureLedger"]

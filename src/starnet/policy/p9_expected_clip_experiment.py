"""Development-only expected-clipped prior injection for bounded P8."""

from __future__ import annotations

from typing import Mapping
from unittest.mock import patch

from starnet.policy.baseline import public_response
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy import p8_experiment
from starnet.policy.structural import public_positive_graph_gate_closed


_ORIGINAL_RESPONSE_FN = p8_experiment._response_fn


def expected_clipped_untried_delta(opinion: float, turn: int) -> float:
    """Return E[min(15*r*slot, 100-w)] for r ~ Uniform(0.2, 1.5)."""
    if turn not in (1, 2, 3):
        return 0.0
    if not -100.0 <= opinion <= 100.0:
        raise ValueError("expected-clip experiment requires an in-bound opinion")
    multiplier = 0.5 ** (turn - 1)
    low, high = 3.0 * multiplier, 22.5 * multiplier
    room = 100.0 - float(opinion)
    if room <= low:
        return max(0.0, room)
    if room >= high:
        return (low + high) / 2.0
    return (room * high - 0.5 * room * room - 0.5 * low * low) / (high - low)


def _expected_response_fn(board, observed: Mapping[int, float]):
    # Preserve P8's positive-graph pooling rule; this experiment changes only
    # the fixed untried prior used on mixed/risky public graphs.
    if public_positive_graph_gate_closed(board):
        return _ORIGINAL_RESPONSE_FN(board, observed)

    def estimate(node_id, node, turn):
        if node_id in observed:
            return public_response(
                node_id, node.persona, turn, observed, DEFAULT_CALIBRATION_PROFILE,
            )
        return expected_clipped_untried_delta(float(node.w), turn)

    return estimate


def choose_expected_clip_action(
    board,
    budget,
    observed,
    *,
    remaining_steps,
    salt,
    mode="conservative",
    evaluation_cache=None,
):
    """Run unchanged P8 while injecting the expected-clipped prior."""
    with patch.object(p8_experiment, "_response_fn", side_effect=_expected_response_fn):
        return p8_experiment.choose_p8_action(
            board,
            budget,
            observed,
            remaining_steps=remaining_steps,
            salt=salt,
            mode=mode,
            evaluation_cache=evaluation_cache,
        )


__all__ = ["choose_expected_clip_action", "expected_clipped_untried_delta"]

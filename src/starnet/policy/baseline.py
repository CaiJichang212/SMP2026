"""Conservative P1 persuasion allocation.

No topology action is constructed in this module.  It intentionally works from
the scanned graph only and returns one independently legal communication slot
per eligible node, so a fresh maximum can be selected after every public
response.
"""

from __future__ import annotations

from collections.abc import Mapping
import math

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.calibration import CalibrationProfile
from starnet.policy.candidates import Candidate


def _turn(node_comm_left: int) -> int:
    """Map verified remaining slots to the next 1/2/3 diminishing slot."""
    return 4 - node_comm_left


def _response(
    node_id: int, persona: str, turn: int, responses: Mapping[int, float], profile: CalibrationProfile
) -> float:
    observed = responses.get(node_id)
    if observed is not None and math.isfinite(observed):
        # The stored observation is always the first successful response for
        # this node.  Later legal slots have the published 1, 1/2, 1/4
        # marginal multiplier; do not rank a repeated persuasion as if it
        # were another first attempt.
        return max(0.0, float(observed)) * (1.0, 0.5, 0.25)[turn - 1]
    prior = profile.response_prior(persona, 1, turn) if profile.verified else None
    return max(0.0, prior[0]) if prior is not None else 1.0


def persuasion_candidates(
    blackboard: Blackboard,
    budget: float,
    responses: Mapping[int, float],
    profile: CalibrationProfile,
    *,
    use_influence: bool = False,
    failed_actions: frozenset[str] | set[str] = frozenset(),
) -> list[Candidate]:
    """Return stable B1/B2 communication candidates with non-negative gain.

    B1 uses exact observed degree times a response estimate. B2 may replace the
    degree term only when the frozen calibration profile contains a held-out
    influence coefficient for that target. Missing coefficients fail back to
    the B1 term; a caller must not claim a B2 result in that case.
    """
    result: list[Candidate] = []
    for node_id, node in sorted(blackboard.nodes.items()):
        if node.comm_left is None or node.comm_left <= 0:
            continue
        turn = _turn(node.comm_left)
        if turn not in (1, 2, 3):
            continue
        action = Action("comm", node_id, prompt_id=1)
        candidate_id = f"comm:{node_id}:{turn}"
        if candidate_id in failed_actions:
            continue
        if not is_legal_action(action, blackboard, budget):
            continue
        degree = sum(node_id in edge for edge in blackboard.edges)
        response = _response(node_id, node.persona, turn, responses, profile)
        coefficient = float(degree)
        if use_influence:
            raw_h = profile.target_influence.get(str(node_id))
            if raw_h is not None and math.isfinite(float(raw_h)):
                coefficient = max(0.0, float(raw_h))
        gain = coefficient * response
        if gain <= 0.0:
            continue
        result.append(
            Candidate(
                candidate_id=candidate_id,
                action=action,
                priority=0,
                score=gain,
                roi=gain / action_cost(action),
                reason=("held-out influence" if use_influence else "observed degree")
                + f" × response, slot {turn}",
            )
        )
    return sorted(result, key=lambda item: (-item.roi, item.candidate_id))


__all__ = ["persuasion_candidates"]

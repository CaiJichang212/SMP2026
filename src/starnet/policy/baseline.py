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
from starnet.policy.cmg import ResponseLedger
from starnet.policy.candidates import Candidate


_PROMPT_ONE_UNIT_RESPONSE = 15.0
_ONLINE_RESPONSE_PRIOR_WEIGHT = 3.0
# The local response distribution used for the explicit public-greedy
# experiment is r ~ Uniform(0.2, 1.5), so its public first-slot mean is
# 15 * (0.2 + 1.5) / 2 = 12.75.  This is a prior, never an environment field.
_PUBLIC_UNTRIED_RESPONSE_PRIOR = 12.75


def _turn(node_comm_left: int) -> int:
    """Map verified remaining slots to the next 1/2/3 diminishing slot."""
    return 4 - node_comm_left


def _marginal_multiplier(turn: int) -> float:
    """Return the published diminishing multiplier for a legal slot."""
    return {1: 1.0, 2: 0.5, 3: 0.25}.get(turn, 0.0)


def _public_influence_coefficients(blackboard: Blackboard) -> dict[int, float]:
    """Return exact, topology-local communication coefficients for B1.

    The qualified offline settlement relation is linear in an unchanged
    component's opinions::

        |C| / sum_j(degree(j) + 1) * sum_i((degree(i) + 1) * w_i)

    Thus a one-unit successful communication on ``i`` changes its component
    score by the returned coefficient.  This calculation uses only the
    already scanned live graph; it neither predicts an unobserved response nor
    enables a cut or shield action.  In particular, an isolated node has a
    non-zero coefficient (one), unlike the former raw-degree proxy.
    """
    node_ids = set(blackboard.nodes)
    adjacency = {node_id: set() for node_id in node_ids}
    for left, right in blackboard.edges:
        if left in node_ids and right in node_ids:
            adjacency[left].add(right)
            adjacency[right].add(left)

    coefficients: dict[int, float] = {}
    unseen = set(node_ids)
    while unseen:
        start = min(unseen)
        component: list[int] = []
        stack = [start]
        unseen.remove(start)
        while stack:
            node_id = stack.pop()
            component.append(node_id)
            for neighbor in adjacency[node_id]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        denominator = sum(len(adjacency[node_id]) + 1 for node_id in component)
        if denominator <= 0:  # Defensive only; every live node contributes one.
            continue
        scale = len(component) / denominator
        coefficients.update(
            {node_id: scale * (len(adjacency[node_id]) + 1) for node_id in component}
        )
    return coefficients


def _response(
    node_id: int, persona: str, turn: int, responses: Mapping[int, float], profile: CalibrationProfile,
    ledger: ResponseLedger | None = None,
) -> float:
    observed = responses.get(node_id)
    if observed is not None and math.isfinite(observed):
        # The stored observation is always the first successful response for
        # this node.  Later legal slots have the published 1, 1/2, 1/4
        # marginal multiplier; do not rank a repeated persuasion as if it
        # were another first attempt.
        return max(0.0, float(observed)) * _marginal_multiplier(turn)

    # ``responses`` contains only first successful public responses.  With no
    # literal calibrated profile, use their pooled mean for an untried node
    # instead of treating every new target as a one-unit response.  Otherwise
    # the first observed target is spuriously preferred for its second/third
    # slot over every equally promising untried target.  P1 found no persona
    # difference when the response coefficient was controlled, so pooling is
    # both less noisy and avoids encoding a hidden persona/rule assumption.
    # A target's own response above always takes precedence.
    pooled = [float(value) for value in responses.values() if math.isfinite(value)]
    if pooled:
        # The response table establishes +15 for prompt 1 at unit response
        # coefficient.  Three pseudo-observations prevent one unusually high
        # or low first target from immediately steering every untried target;
        # public observations take over quickly as the session progresses.
        return _marginal_multiplier(turn) * max(
            0.0,
            (
                _ONLINE_RESPONSE_PRIOR_WEIGHT * _PROMPT_ONE_UNIT_RESPONSE + sum(pooled)
            ) / (_ONLINE_RESPONSE_PRIOR_WEIGHT + len(pooled)),
        )

    if ledger is not None:
        # A reviewed profile may carry a usable persona-specific prior before
        # this session has any public response.  The default profile does not.
        posterior = ledger.predicted_delta(node_id, persona, 1, profile, turn=turn)
        if posterior is not None and math.isfinite(posterior[0]):
            return max(0.0, float(posterior[0]))
    prior = profile.response_prior(persona, 1, turn) if profile.verified else None
    return max(0.0, prior[0]) if prior is not None else (
        _PROMPT_ONE_UNIT_RESPONSE * _marginal_multiplier(turn)
    )


def public_response(
    node_id: int, persona: str, turn: int, responses: Mapping[int, float],
    profile: CalibrationProfile, ledger: ResponseLedger | None = None,
) -> float:
    """Estimate an experimental slot without pooling unrelated targets.

    ``responses`` stores only a node's first successful public response.  A
    tried node therefore uses its own observed value with the published
    diminishing multiplier.  An untried node uses a fixed population prior;
    one unusually high or low observation must not change every other target's
    expected response.  A verified profile may replace that prior with its
    own held-out response prior, while the unverified public experiment uses
    the fixed 12.75 unit prior above.
    """
    observed = responses.get(node_id)
    if observed is not None and math.isfinite(observed):
        return max(0.0, float(observed)) * _marginal_multiplier(turn)
    if profile.verified:
        prior = profile.response_prior(persona, 1, turn)
        if prior is not None and math.isfinite(prior[0]):
            return max(0.0, float(prior[0]))
    return _PUBLIC_UNTRIED_RESPONSE_PRIOR * _marginal_multiplier(turn)


def persuasion_candidates(
    blackboard: Blackboard,
    budget: float,
    responses: Mapping[int, float],
    profile: CalibrationProfile,
    *,
    use_influence: bool = False,
    failed_actions: frozenset[str] | set[str] = frozenset(),
    ledger: ResponseLedger | None = None,
) -> list[Candidate]:
    """Return stable B1/B2 communication candidates with non-negative gain.

    B1 multiplies a response estimate by an exact coefficient from the public,
    scanned connected component. B2 may replace that coefficient only when the
    frozen calibration profile contains a held-out target coefficient. Missing
    coefficients fail back to B1; a caller must not claim a B2 result in that
    case.
    """
    result: list[Candidate] = []
    public_influence = _public_influence_coefficients(blackboard)
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
        response = _response(node_id, node.persona, turn, responses, profile, ledger)
        coefficient = public_influence.get(node_id, 0.0)
        reason = "public component influence"
        if use_influence:
            raw_h = profile.target_influence.get(str(node_id))
            if raw_h is not None and math.isfinite(float(raw_h)):
                coefficient = max(0.0, float(raw_h))
                reason = "held-out influence"
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
                reason=reason + f" × response, slot {turn}",
            )
        )
    return sorted(result, key=lambda item: (-item.roi, item.candidate_id))


__all__ = ["persuasion_candidates", "public_response"]

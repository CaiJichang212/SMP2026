"""Preregistered P9 distribution-shift seeds for offline evaluation only.

The response factor ``r`` is hidden environment state. Submission policies
must learn responses only from public action returns and must never import
this module. Development and confirmation repetitions are disjoint; callers
must explicitly unlock the reserved confirmation cohort.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

import networkx as nx


FAMILIES = ("er_resampled", "ba_resampled", "ws_resampled", "sbm_resampled")
SHIFT_STRATA = (
    "centered_independent",
    "negative_persona_aligned",
    "positive_persona_inverse",
    "wide_degree_positive",
    "compressed_degree_negative",
    "near_upper_bound",
    "saturated_hubs",
)
DEVELOPMENT_REPETITIONS = (901, 902)
CONFIRMATION_REPETITIONS = (1001, 1002, 1003, 1004, 1005)

_W_TRANSFORMS = {
    "centered_independent": (1.0, 0.0),
    "negative_persona_aligned": (1.25, -8.0),
    "positive_persona_inverse": (0.8, 8.0),
    "wide_degree_positive": (1.6, -2.0),
    "compressed_degree_negative": (0.6, 2.0),
}


def _rng(family: str, repetition: int, stream: str) -> random.Random:
    material = f"SMP2026:P9:{family}:{repetition}:{stream}".encode("ascii")
    return random.Random(int.from_bytes(hashlib.sha256(material).digest()[:8], "big"))


def _connect(graph: nx.Graph, rng: random.Random) -> nx.Graph:
    components = [sorted(component) for component in nx.connected_components(graph)]
    components.sort(key=lambda component: component[0])
    for left, right in zip(components, components[1:]):
        graph.add_edge(rng.choice(left), rng.choice(right))
    return graph


def _graph(family: str, count: int, rng: random.Random) -> nx.Graph:
    if family == "er_resampled":
        return _connect(nx.gnp_random_graph(count, rng.uniform(0.06, 0.14), seed=rng), rng)
    if family == "ba_resampled":
        return nx.barabasi_albert_graph(count, rng.choice((2, 3, 4, 5)), seed=rng)
    if family == "ws_resampled":
        return nx.connected_watts_strogatz_graph(
            count, rng.choice((4, 6, 8)), rng.uniform(0.08, 0.45), tries=200, seed=rng,
        )
    if family == "sbm_resampled":
        first = rng.randint(13, 19)
        second = rng.randint(13, 19)
        sizes = [first, second, count - first - second]
        inside = rng.uniform(0.12, 0.25)
        outside = rng.uniform(0.008, 0.04)
        probabilities = [
            [inside, outside, outside],
            [outside, inside * rng.uniform(0.75, 1.15), outside],
            [outside, outside, inside * rng.uniform(0.75, 1.15)],
        ]
        return _connect(nx.stochastic_block_model(sizes, probabilities, seed=rng), rng)
    raise ValueError(f"unknown P9 family: {family}")


def _base_opinion(rng: random.Random) -> tuple[str, float]:
    roll = rng.random()
    if roll < 0.36:
        return "和平", rng.uniform(2.0, 30.0)
    if roll < 0.72:
        return "中立", rng.uniform(-12.0, 12.0)
    return "暴力", rng.uniform(-38.0, -3.0)


def _response(
    stratum: str, persona: str, degree: int, min_degree: int, max_degree: int,
    rng: random.Random,
) -> float:
    if stratum in {"centered_independent", "near_upper_bound"}:
        return rng.uniform(0.2, 1.5)
    if stratum in {"negative_persona_aligned", "positive_persona_inverse"}:
        aligned = {"和平": (1.05, 1.5), "中立": (0.55, 1.1), "暴力": (0.2, 0.65)}
        inverse = {"和平": (0.2, 0.65), "中立": (0.55, 1.1), "暴力": (1.05, 1.5)}
        low, high = (aligned if stratum == "negative_persona_aligned" else inverse)[persona]
        return rng.uniform(low, high)
    span = max(1, max_degree - min_degree)
    degree_fraction = (degree - min_degree) / span
    if stratum in {"wide_degree_positive", "saturated_hubs"}:
        center = 0.2 + 1.3 * degree_fraction
    elif stratum == "compressed_degree_negative":
        center = 1.5 - 1.3 * degree_fraction
    else:
        raise ValueError(f"unknown P9 shift stratum: {stratum}")
    return min(1.5, max(0.2, center + rng.uniform(-0.06, 0.06)))


def seed_payload(
    family: str,
    repetition: int,
    shift_stratum: str = "centered_independent",
    node_count: int = 50,
    *,
    allow_confirmation: bool = False,
) -> dict[str, Any]:
    """Return one deterministic P9 seed from the preregistered Cartesian cohort."""
    if family not in FAMILIES:
        raise ValueError(f"unknown P9 family: {family}")
    if shift_stratum not in SHIFT_STRATA:
        raise ValueError(f"unknown P9 shift stratum: {shift_stratum}")
    if node_count != 50:
        raise ValueError("P9 distribution validation is fixed to 50 nodes")
    if repetition in CONFIRMATION_REPETITIONS and not allow_confirmation:
        raise ValueError("P9 confirmation cohort is reserved")
    if repetition not in DEVELOPMENT_REPETITIONS + CONFIRMATION_REPETITIONS:
        raise ValueError("repetition is outside the preregistered P9 cohorts")

    graph = _graph(family, node_count, _rng(family, repetition, "topology"))
    label_rng = _rng(family, repetition, "labels")
    labels = list(range(1, node_count + 1))
    label_rng.shuffle(labels)
    remap = dict(enumerate(labels))

    opinion_rng = _rng(family, repetition, "opinions")
    base = {node_id: _base_opinion(opinion_rng) for node_id in range(node_count)}
    degrees = dict(graph.degree())
    min_degree, max_degree = min(degrees.values()), max(degrees.values())
    ranked_by_degree = sorted(degrees, key=lambda node_id: (-degrees[node_id], remap[node_id]))
    saturated = set(ranked_by_degree[: max(1, node_count // 5)])
    boundary_rng = _rng(family, repetition, "boundary-opinions")
    response_rng = _rng(family, repetition, f"responses:{shift_stratum}")
    nodes = []
    for original in range(node_count):
        persona, opinion = base[original]
        if shift_stratum == "near_upper_bound":
            transformed = 80.0 + 20.0 * (opinion + 38.0) / 68.0
        elif shift_stratum == "saturated_hubs" and original in saturated:
            persona = "和平"
            transformed = boundary_rng.uniform(90.0, 100.0)
        else:
            scale, offset = _W_TRANSFORMS.get(shift_stratum, (1.0, 0.0))
            transformed = min(60.0, max(-60.0, scale * opinion + offset))
        nodes.append({
            "id": remap[original],
            "w": round(transformed, 6),
            "persona": persona,
            "r": round(_response(
                shift_stratum, persona, degrees[original], min_degree, max_degree, response_rng,
            ), 6),
            "comm_left": 3,
        })
    nodes.sort(key=lambda item: item["id"])
    edges = sorted(
        [min(remap[left], remap[right]), max(remap[left], remap[right])]
        for left, right in graph.edges()
    )
    return {
        "global_setting": {"max_budget": 100.0, "max_api_calls": 120},
        "original_total": round(sum(node["w"] for node in nodes), 6),
        "nodes": nodes,
        "edges": edges,
        "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
    }


__all__ = [
    "CONFIRMATION_REPETITIONS",
    "DEVELOPMENT_REPETITIONS",
    "FAMILIES",
    "SHIFT_STRATA",
    "seed_payload",
]

"""Fresh P10 confirmation seeds, closed unless explicitly unlocked."""

from __future__ import annotations

import hashlib
import random
from typing import Any

from starnet.experiments.p9_distribution_seeds import _base_opinion, _graph


FAMILIES = ("er_resampled", "ba_resampled", "ws_resampled", "sbm_resampled")
STRATA = ("independent", "aligned_contaminated", "inverse_contaminated", "degree_correlated")
CONFIRMATION_REPETITIONS = (1201, 1202, 1203)


def _rng(family: str, repetition: int, stream: str) -> random.Random:
    material = f"SMP2026:P10:{family}:{repetition}:{stream}".encode("ascii")
    return random.Random(int.from_bytes(hashlib.sha256(material).digest()[:8], "big"))


def _conditional_range(stratum: str, persona: str) -> tuple[float, float]:
    if persona == "中立" or stratum == "independent":
        return 0.2, 1.5
    aligned = stratum == "aligned_contaminated"
    if persona == "和平":
        return (1.05, 1.5) if aligned else (0.2, 0.65)
    return (0.2, 0.65) if aligned else (1.05, 1.5)


def _response(
    stratum: str, persona: str, degree: int, min_degree: int, max_degree: int,
    rng: random.Random,
) -> float:
    if stratum in {"aligned_contaminated", "inverse_contaminated"}:
        bounds = (
            (0.2, 1.5)
            if rng.random() < 0.2
            else _conditional_range(stratum, persona)
        )
        return rng.uniform(*bounds)
    if stratum == "independent":
        return rng.uniform(0.2, 1.5)
    if stratum == "degree_correlated":
        fraction = (degree - min_degree) / max(1, max_degree - min_degree)
        return min(1.5, max(0.2, 0.2 + 1.3 * fraction + rng.uniform(-0.06, 0.06)))
    raise ValueError("unknown P10 response stratum")


def seed_payload(
    family: str, repetition: int, stratum: str, node_count: int = 50, *,
    allow_confirmation: bool = False,
) -> dict[str, Any]:
    if not allow_confirmation:
        raise ValueError("P10 confirmation seeds are reserved; explicit unlock required")
    if family not in FAMILIES or stratum not in STRATA:
        raise ValueError("unknown P10 family or stratum")
    if repetition not in CONFIRMATION_REPETITIONS or node_count != 50:
        raise ValueError("P10 confirmation is fixed to repetitions 1201-1203 and 50 nodes")

    graph = _graph(family, node_count, _rng(family, repetition, "topology"))
    label_rng = _rng(family, repetition, "labels")
    labels = list(range(1, node_count + 1))
    label_rng.shuffle(labels)
    remap = dict(enumerate(labels))
    opinion_rng = _rng(family, repetition, "opinions")
    opinions = {node_id: _base_opinion(opinion_rng) for node_id in range(node_count)}
    degrees = dict(graph.degree())
    minimum, maximum = min(degrees.values()), max(degrees.values())
    response_rng = _rng(family, repetition, f"responses:{stratum}")
    nodes = []
    for original in range(node_count):
        persona, opinion = opinions[original]
        nodes.append({
            "id": remap[original], "w": round(opinion, 6), "persona": persona,
            "r": round(_response(
                stratum, persona, degrees[original], minimum, maximum, response_rng,
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


__all__ = ["CONFIRMATION_REPETITIONS", "FAMILIES", "STRATA", "seed_payload"]

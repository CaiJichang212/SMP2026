"""Topology-disjoint, reproducible P7 development and confirmation seeds.

The response factor ``r`` belongs to the offline seed and must never be passed
to a production policy. Strata share topology and opinions within a repetition.
"""

from __future__ import annotations

import random
from typing import Any

import networkx as nx


FAMILIES = (
    "random_geometric",
    "barbell",
    "lollipop",
    "random_tree",
    "bipartite",
)
R_STRATA = {
    "low": (0.2, 0.55),
    "standard": (0.2, 1.5),
    "high": (1.1, 1.5),
}
DEVELOPMENT_REPETITIONS = (301, 302, 303)
CONFIRMATION_REPETITIONS = (401, 402, 403, 404, 405)


def _rng(family: str, repetition: int, stream: int) -> random.Random:
    family_code = sum((index + 1) * ord(char) for index, char in enumerate(family))
    return random.Random(20260912 + 100_003 * repetition + 997 * family_code + stream)


def _graph(family: str, count: int, rng: random.Random) -> nx.Graph:
    if family == "random_geometric":
        return nx.random_geometric_graph(count, radius=0.22, seed=rng)
    if family == "barbell":
        clique = rng.randint(count // 4, count // 3)
        return nx.barbell_graph(clique, count - 2 * clique)
    if family == "lollipop":
        clique = rng.randint(count // 3, count // 2)
        return nx.lollipop_graph(clique, count - clique)
    if family == "random_tree":
        return nx.random_labeled_tree(count, seed=rng)
    if family == "bipartite":
        left = count // 2
        return nx.bipartite.random_graph(left, count - left, 0.15, seed=rng)
    raise ValueError(f"unknown P7 family: {family}")


def _opinion(family: str, node: int, count: int, rng: random.Random) -> tuple[str, float]:
    if family == "barbell" and node < count // 4:
        return "暴力", rng.uniform(-40.0, -10.0)
    if family == "barbell" and node >= count - count // 4:
        return "和平", rng.uniform(6.0, 26.0)
    if family == "lollipop" and node < count // 3:
        return "暴力", rng.uniform(-38.0, -8.0)
    if family == "bipartite" and node < count // 2:
        return "暴力", rng.uniform(-32.0, -4.0)
    if family == "bipartite":
        return "和平", rng.uniform(4.0, 26.0)
    roll = rng.random()
    if roll < 0.42:
        return "和平", rng.uniform(4.0, 26.0)
    if roll < 0.8:
        return "中立", rng.uniform(-8.0, 8.0)
    return "暴力", rng.uniform(-30.0, -4.0)


def seed_payload(
    family: str,
    repetition: int,
    r_stratum: str = "standard",
    node_count: int = 50,
) -> dict[str, Any]:
    """Build a legal custom seed with independent topology per repetition."""
    if family not in FAMILIES:
        raise ValueError(f"unknown P7 family: {family}")
    if r_stratum not in R_STRATA:
        raise ValueError(f"unknown response stratum: {r_stratum}")
    if node_count != 50 or repetition <= 0:
        raise ValueError("P7 currently defines positive-repetition 50-node seeds only")

    topology_rng = _rng(family, repetition, 1)
    opinion_rng = _rng(family, repetition, 2)
    label_rng = _rng(family, repetition, 3)
    response_rng = _rng(family, repetition, 4 + list(R_STRATA).index(r_stratum))
    graph = _graph(family, node_count, topology_rng)
    labels = list(range(1, node_count + 1))
    label_rng.shuffle(labels)
    remap = dict(enumerate(labels))
    low, high = R_STRATA[r_stratum]
    nodes = []
    for original in range(node_count):
        persona, opinion = _opinion(family, original, node_count, opinion_rng)
        nodes.append({
            "id": remap[original],
            "w": round(opinion, 6),
            "persona": persona,
            "r": round(response_rng.uniform(low, high), 6),
            "comm_left": 3,
        })
    nodes.sort(key=lambda item: item["id"])
    edges = sorted([min(remap[left], remap[right]), max(remap[left], remap[right])]
                   for left, right in graph.edges())
    return {
        "global_setting": {"max_budget": 100.0, "max_api_calls": 120},
        "original_total": round(sum(node["w"] for node in nodes), 6),
        "nodes": nodes,
        "edges": edges,
        "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
    }

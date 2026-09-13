"""P8 seed distribution with four new families and one uniform wrapper.

Response factor ``r`` is offline environment data. Production policies must
only learn responses from public action returns and never import this module.
The ``degree_corrected_sbm`` family is a synthetic approximation made from a
random-partition graph plus heterogeneous hub edges, not a formal DCSBM draw.
Historical fixed-topology families retain their topology semantics; only the
four new families guarantee independent topology and ID permutation by repeat.
"""

from __future__ import annotations

import random
from typing import Any, Callable

import networkx as nx

from starnet.experiments.p7_seeds import FAMILIES as P7_FAMILIES
from starnet.experiments.p7_seeds import seed_payload as p7_seed_payload
from starnet.experiments.seeds import SEED_SPECS
from starnet.experiments.seeds import seed_payload as existing_seed_payload


NEW_FAMILIES = (
    "degree_corrected_sbm",
    "powerlaw_cluster",
    "watts_strogatz_mixed",
    "random_regular_mixed",
)
DEVELOPMENT_REPETITIONS = (501, 502, 503)
CONFIRMATION_REPETITIONS = (601, 602, 603, 604, 605)
R_STRATA = ("standard", "low", "high", "persona_correlated")


def _legacy_generators() -> dict[str, Callable[[str, int, int], dict[str, Any]]]:
    # Delayed import keeps the production package independent of experiment
    # runners while providing one interface across all historical families.
    from scripts.run_local_policy_matrix import (
        HOLDOUT_FAMILIES,
        INDEPENDENT_FAMILIES,
        holdout_seed_payload,
        independent_seed_payload,
    )

    result = {family: existing_seed_payload for family in SEED_SPECS}
    result.update({family: independent_seed_payload for family in INDEPENDENT_FAMILIES})
    result.update({family: holdout_seed_payload for family in HOLDOUT_FAMILIES})
    return result


OLD_FAMILIES = (
    *tuple(SEED_SPECS),
    "grid_lattice", "cycle_chords", "two_block_bridge", "tree_broom",
    "double_bridge_communities", "ring_of_cliques", "negative_hub_spokes",
    *P7_FAMILIES,
)
FAMILIES = (*OLD_FAMILIES, *NEW_FAMILIES)


def _rng(family: str, repetition: int, stream: int) -> random.Random:
    family_code = sum((index + 11) * ord(char) for index, char in enumerate(family))
    return random.Random(20260913 + 1_000_003 * repetition + 10_007 * family_code + stream)


def _new_graph(family: str, count: int, rng: random.Random) -> nx.Graph:
    if family == "degree_corrected_sbm":
        graph = nx.random_partition_graph([17, 16, count - 33], 0.16, 0.015, seed=rng)
        # Add a few preferential in-community links to vary degrees within blocks.
        partitions = (range(0, 17), range(17, 33), range(33, count))
        for group in partitions:
            members = list(group)
            hub = rng.choice(members)
            for node in members:
                if node != hub and rng.random() < 0.5:
                    graph.add_edge(hub, node)
        return graph
    if family == "powerlaw_cluster":
        return nx.powerlaw_cluster_graph(count, 3, 0.35, seed=rng)
    if family == "watts_strogatz_mixed":
        return nx.watts_strogatz_graph(count, rng.choice((4, 6, 8)), 0.28, seed=rng)
    if family == "random_regular_mixed":
        return nx.random_regular_graph(rng.choice((3, 4, 5, 6)), count, seed=rng)
    raise ValueError(f"unknown P8 family: {family}")


def _new_opinion(family: str, original: int, count: int, rng: random.Random) -> tuple[str, float]:
    if family == "degree_corrected_sbm" and original < 17:
        return "暴力", rng.uniform(-36.0, -7.0)
    if family == "degree_corrected_sbm" and original >= 33:
        return "和平", rng.uniform(5.0, 25.0)
    roll = rng.random()
    if roll < 0.4:
        return "和平", rng.uniform(4.0, 26.0)
    if roll < 0.78:
        return "中立", rng.uniform(-9.0, 9.0)
    return "暴力", rng.uniform(-32.0, -4.0)


def _new_seed(family: str, repetition: int, node_count: int) -> dict[str, Any]:
    topology_rng = _rng(family, repetition, 1)
    opinion_rng = _rng(family, repetition, 2)
    label_rng = _rng(family, repetition, 3)
    graph = _new_graph(family, node_count, topology_rng)
    labels = list(range(1, node_count + 1))
    label_rng.shuffle(labels)
    remap = dict(enumerate(labels))
    nodes = []
    for original in range(node_count):
        persona, opinion = _new_opinion(family, original, node_count, opinion_rng)
        nodes.append({"id": remap[original], "w": round(opinion, 6), "persona": persona,
                      "r": 1.0, "comm_left": 3})
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


def _response(rng: random.Random, stratum: str, persona: str) -> float:
    if stratum == "standard":
        return rng.uniform(0.2, 1.5)
    if stratum == "low":
        return rng.uniform(0.2, 0.55)
    if stratum == "high":
        return rng.uniform(1.1, 1.5)
    ranges = {"和平": (1.05, 1.5), "中立": (0.55, 1.1), "暴力": (0.2, 0.65)}
    low, high = ranges.get(persona, (0.2, 1.5))
    return rng.uniform(low, high)


def seed_payload(
    family: str,
    repetition: int,
    r_stratum: str = "standard",
    node_count: int = 50,
) -> dict[str, Any]:
    """Return one P8 seed across the 18 historical and four new families.

    Every response stratum, including ``standard``, is sampled by this P8
    wrapper. Therefore an old-family P8 seed is not hash-compatible with an
    earlier P7 seed that happens to use the same repetition number.
    """
    if family not in FAMILIES:
        raise ValueError(f"unknown P8 family: {family}")
    if r_stratum not in R_STRATA:
        raise ValueError(f"unknown response stratum: {r_stratum}")
    if node_count != 50 or repetition <= 0:
        raise ValueError("P8 currently defines positive-repetition 50-node seeds only")

    if family in NEW_FAMILIES:
        seed = _new_seed(family, repetition, node_count)
    elif family in P7_FAMILIES:
        seed = p7_seed_payload(family, repetition, "standard", node_count)
    else:
        seed = _legacy_generators()[family](family, node_count, repetition)
    response_rng = _rng(family, repetition, 10 + R_STRATA.index(r_stratum))
    for node in seed["nodes"]:
        node["r"] = round(_response(response_rng, r_stratum, str(node["persona"])), 6)
    return seed


__all__ = [
    "CONFIRMATION_REPETITIONS",
    "DEVELOPMENT_REPETITIONS",
    "FAMILIES",
    "NEW_FAMILIES",
    "OLD_FAMILIES",
    "R_STRATA",
    "seed_payload",
]

"""Fixed, generated 50-node seeds for V0 comparisons.

The generator is intentionally part of source control rather than a directory
of opaque JSON assets.  ``seed_payload`` is deterministic across runs and can
be hashed before uploading to a fresh remote session.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from typing import Any

import networkx as nx


SEED_SPECS: dict[str, int] = {
    "er_balanced": 13011,
    "ba_negative_hubs": 13012,
    "ws_peace_majority": 13013,
    "sbm_negative_bridges": 13014,
    "sbm_violent_cluster": 13015,
    "three_sparse_components": 13016,
}


def _components_edges(groups: Iterable[list[int]], rng: random.Random) -> nx.Graph:
    graph = nx.Graph()
    for group in groups:
        graph.add_nodes_from(group)
        for left, right in zip(group, group[1:]):
            graph.add_edge(left, right)
        for index, left in enumerate(group):
            for right in group[index + 2 :]:
                if rng.random() < 0.055:
                    graph.add_edge(left, right)
    return graph


def _graph_for(name: str, rng: random.Random, node_count: int = 50) -> nx.Graph:
    seed = SEED_SPECS[name] if node_count == 50 else SEED_SPECS[name] + node_count * 1009
    if name == "er_balanced":
        return nx.gnp_random_graph(node_count, 0.12, seed=seed)
    if name == "ba_negative_hubs":
        return nx.barabasi_albert_graph(node_count, min(3, node_count - 1), seed=seed)
    if name == "ws_peace_majority":
        return nx.watts_strogatz_graph(node_count, min(6, node_count - 1), 0.18, seed=seed)
    if name in {"sbm_negative_bridges", "sbm_violent_cluster"}:
        sizes = [node_count // 2, node_count - node_count // 2]
        probabilities = [[0.20, 0.025], [0.025, 0.20]]
        return nx.stochastic_block_model(sizes, probabilities, seed=seed)
    if name == "three_sparse_components":
        first = node_count // 3
        second = 2 * node_count // 3
        return _components_edges([list(range(0, first)), list(range(first, second)), list(range(second, node_count))], rng)
    raise KeyError(f"unknown experiment seed {name}")


def _node_data(name: str, graph: nx.Graph, rng: random.Random) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    node_count = graph.number_of_nodes()
    hubs = sorted(graph.degree, key=lambda item: (-item[1], item[0]))
    hub_ids = {node_id for node_id, _ in hubs[:8]}
    sbm_boundary = node_count // 2
    sbm_bridge_ids = set(range(max(0, sbm_boundary - 2), min(node_count, sbm_boundary + 2)))
    # ``_components_edges`` guarantees a path in each requested group.  The
    # final connected component is therefore the topology-defined final third,
    # not a 50-node literal threshold.
    final_component = max(nx.connected_components(graph), key=lambda component: max(component), default=set())
    for zero_id in sorted(graph.nodes):
        node_id = int(zero_id) + 1
        persona = "中立"
        weight = rng.uniform(-8.0, 8.0)
        if name == "ba_negative_hubs" and zero_id in hub_ids:
            persona, weight = "暴力", rng.uniform(-45.0, -20.0)
        elif name == "ws_peace_majority":
            persona = "和平" if rng.random() < 0.72 else "中立"
            weight = rng.uniform(3.0, 22.0) if persona == "和平" else rng.uniform(-3.0, 5.0)
        elif name == "sbm_negative_bridges" and zero_id in sbm_bridge_ids:
            persona, weight = "暴力", rng.uniform(-42.0, -20.0)
        elif name == "sbm_violent_cluster" and zero_id < sbm_boundary:
            persona, weight = "暴力", rng.uniform(-40.0, -12.0)
        elif name == "three_sparse_components" and zero_id in final_component:
            persona, weight = "暴力", rng.uniform(-32.0, -8.0)
        else:
            roll = rng.random()
            persona = "和平" if roll < 0.42 else "中立" if roll < 0.82 else "暴力"
            if persona == "和平":
                weight = rng.uniform(4.0, 26.0)
            elif persona == "暴力":
                weight = rng.uniform(-30.0, -4.0)
        nodes.append(
            {
                "id": node_id,
                "w": round(weight, 6),
                "persona": persona,
                "r": round(rng.uniform(0.2, 1.5), 6),
                "comm_left": 3,
            }
        )
    return nodes


def seed_payload(name: str, node_count: int = 50, repetition: int = 1) -> dict[str, Any]:
    """Return one complete, portable custom-seed payload."""
    if node_count <= 0 or repetition <= 0:
        raise ValueError("node_count and repetition must be positive")
    base_seed = SEED_SPECS[name] + (node_count - 50) * 1009 + (repetition - 1) * 7919
    rng = random.Random(base_seed)
    graph = _graph_for(name, rng, node_count)
    graph.add_nodes_from(range(node_count))
    nodes = _node_data(name, graph, rng)
    return {
        "global_setting": {"max_budget": 100.0 if node_count <= 50 else 200.0,
                            "max_api_calls": 120 if node_count <= 50 else 250},
        "original_total": round(sum(node["w"] for node in nodes), 6),
        "nodes": nodes,
        "edges": [[int(left) + 1, int(right) + 1] for left, right in sorted(graph.edges)],
        "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
    }


def all_seed_payloads() -> dict[str, dict[str, Any]]:
    return {name: seed_payload(name) for name in SEED_SPECS}


def matrix_seed_payloads(*, node_counts: tuple[int, ...] = (50, 100), repetitions: int = 2) -> dict[str, dict[str, Any]]:
    """Return deterministic fast-screen seeds (six topologies × sizes × reps)."""
    if repetitions <= 0:
        raise ValueError("repetitions must be positive")
    return {
        f"{name}-{node_count}-r{repetition}": seed_payload(name, node_count, repetition)
        for name in SEED_SPECS
        for node_count in node_counts
        for repetition in range(1, repetitions + 1)
    }


def validation_seed_payloads() -> dict[str, dict[str, Any]]:
    """Return the independent 120-seed matrix requested for final validation."""
    return {
        f"{name}-{node_count}-r{repetition}": seed_payload(name, node_count, repetition)
        for name in SEED_SPECS
        for node_count in (50, 100)
        for repetition in range(1, 11)
    }

"""Experiment-only topology cache for exact component settlement scores."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TypeAlias

from starnet.policy.cmg import PredictiveState


TopologyKey: TypeAlias = tuple[tuple[int, ...], tuple[tuple[int, int], ...]]


@dataclass(frozen=True)
class _Component:
    nodes: tuple[int, ...]
    factors: tuple[int, ...]
    denominator: int

    @property
    def size(self) -> int:
        return len(self.nodes)


class FastComponentSettlement:
    """Cache topology terms while recomputing every opinion contribution."""

    def __init__(self, max_topologies: int = 128) -> None:
        if isinstance(max_topologies, bool) or max_topologies <= 0:
            raise ValueError("max_topologies must be positive")
        self.max_topologies = max_topologies
        self._cache: OrderedDict[TopologyKey, tuple[_Component, ...]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def topology_key(state: PredictiveState) -> TopologyKey:
        nodes = tuple(sorted(state.nodes))
        node_set = set(nodes)
        edges = tuple(sorted(
            (left, right) if left < right else (right, left)
            for left, right in state.edges
            if left in node_set and right in node_set
        ))
        return nodes, edges

    @staticmethod
    def _compile(key: TopologyKey) -> tuple[_Component, ...]:
        nodes, edges = key
        parent = {node: node for node in nodes}
        degree = {node: 0 for node in nodes}

        def find(node: int) -> int:
            root = node
            while parent[root] != root:
                root = parent[root]
            while parent[node] != node:
                next_node = parent[node]
                parent[node] = root
                node = next_node
            return root

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for left, right in edges:
            degree[left] += 1
            degree[right] += 1
            union(left, right)
        groups: dict[int, list[int]] = {}
        for node in nodes:
            groups.setdefault(find(node), []).append(node)
        ordered = sorted((tuple(group) for group in groups.values()), key=lambda group: group[0])
        return tuple(
            _Component(
                component,
                tuple(degree[node] + 1 for node in component),
                sum(degree[node] + 1 for node in component),
            )
            for component in ordered
        )

    def score(self, state: PredictiveState) -> float:
        if not state.nodes:
            return 0.0
        key = self.topology_key(state)
        components = self._cache.get(key)
        if components is None:
            self.misses += 1
            components = self._compile(key)
            self._cache[key] = components
            if len(self._cache) > self.max_topologies:
                self._cache.popitem(last=False)
        else:
            self.hits += 1
            self._cache.move_to_end(key)

        def component_score(component: _Component) -> float:
            weighted = 0.0
            for node, factor in zip(component.nodes, component.factors):
                weighted += factor * float(state.nodes[node].w)
            return component.size * weighted / component.denominator

        return sum(component_score(component) for component in components)

    @property
    def cache_size(self) -> int:
        return len(self._cache)


__all__ = ["FastComponentSettlement", "TopologyKey"]

"""Tests for deterministic graph-derived policy metrics."""

from __future__ import annotations

import math
import unittest

from starnet.model.blackboard import Blackboard
from starnet.policy.graph_analysis import analyze_graph, build_graph, stable_normalize


def record_node(
    board: Blackboard,
    node_id: int,
    *,
    w: float = 0.0,
    persona: str = "中立",
    comm_left: int = 3,
    neighbors: list[int] | None = None,
) -> None:
    board.record_scan(
        node_id,
        {
            "w": w,
            "persona": persona,
            "comm_left": comm_left,
            "neighbors": [] if neighbors is None else neighbors,
        },
    )


class GraphAnalysisTests(unittest.TestCase):
    def assert_analysis_is_bounded(self, board: Blackboard) -> None:
        analysis = analyze_graph(board)
        for metrics in analysis.node_metrics.values():
            for value in (
                metrics.degree,
                metrics.pagerank,
                metrics.core,
                metrics.betweenness,
                metrics.voterank,
                metrics.influence,
                metrics.positive_influence,
                metrics.danger,
            ):
                self.assertTrue(math.isfinite(value))
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)
        for metrics in analysis.edge_metrics.values():
            self.assertTrue(math.isfinite(metrics.edge_betweenness))
            self.assertTrue(math.isfinite(metrics.negative_flow))
            self.assertGreaterEqual(metrics.edge_betweenness, 0.0)
            self.assertLessEqual(metrics.edge_betweenness, 1.0)
            self.assertGreaterEqual(metrics.negative_flow, 0.0)
            self.assertLessEqual(metrics.negative_flow, 1.0)

    def test_build_graph_uses_only_live_scanned_nodes_and_canonical_edges(self) -> None:
        board = Blackboard()
        record_node(board, 3, neighbors=[1, 9])
        record_node(board, 1, neighbors=[3])

        graph = build_graph(board)

        self.assertEqual(list(graph.nodes), [1, 3])
        self.assertEqual(list(graph.edges), [(1, 3)])
        self.assertIn((3, 9), board.edges)

    def test_stable_normalize_handles_all_zero_and_constant_nonzero_features(self) -> None:
        self.assertEqual(stable_normalize({1: 0.0, 2: 0.0}), {1: 0.0, 2: 0.0})
        self.assertEqual(stable_normalize({1: 4.0, 2: 4.0}), {1: 1.0, 2: 1.0})
        self.assertEqual(stable_normalize({1: 2.0, 2: 6.0}), {1: 0.0, 2: 1.0})

    def test_path_triangle_star_disconnected_singleton_and_edgeless_graphs_are_safe(self) -> None:
        path = Blackboard()
        record_node(path, 1, neighbors=[2])
        record_node(path, 2, neighbors=[1, 3])
        record_node(path, 3, neighbors=[2, 4])
        record_node(path, 4, neighbors=[3])

        triangle = Blackboard()
        record_node(triangle, 1, neighbors=[2, 3])
        record_node(triangle, 2, neighbors=[1, 3])
        record_node(triangle, 3, neighbors=[1, 2])

        star = Blackboard()
        record_node(star, 1, neighbors=[2, 3, 4])
        record_node(star, 2, neighbors=[1])
        record_node(star, 3, neighbors=[1])
        record_node(star, 4, neighbors=[1])

        disconnected = Blackboard()
        record_node(disconnected, 1, neighbors=[2])
        record_node(disconnected, 2, neighbors=[1])
        record_node(disconnected, 10, neighbors=[11])
        record_node(disconnected, 11, neighbors=[10])

        singleton = Blackboard()
        record_node(singleton, 1)

        edgeless = Blackboard()
        record_node(edgeless, 1)
        record_node(edgeless, 2)

        for board in (path, triangle, star, disconnected, singleton, edgeless):
            self.assert_analysis_is_bounded(board)

        self.assertEqual(analyze_graph(edgeless).community_count, 2)

    def test_star_center_has_higher_influence_betweenness_and_danger(self) -> None:
        board = Blackboard()
        record_node(board, 1, w=-10, persona="暴力", neighbors=[2, 3, 4])
        record_node(board, 2, w=2, persona="和平", neighbors=[1])
        record_node(board, 3, w=2, persona="和平", neighbors=[1])
        record_node(board, 4, w=2, persona="和平", neighbors=[1])

        metrics = analyze_graph(board).node_metrics

        self.assertGreater(metrics[1].influence, metrics[2].influence)
        self.assertGreater(metrics[1].betweenness, metrics[2].betweenness)
        self.assertGreater(metrics[1].danger, metrics[2].danger)

    def test_communities_and_voterank_are_repeatable(self) -> None:
        board = Blackboard()
        record_node(board, 1, neighbors=[2, 3])
        record_node(board, 2, neighbors=[1, 3])
        record_node(board, 3, neighbors=[1, 2])
        record_node(board, 10, neighbors=[11, 12])
        record_node(board, 11, neighbors=[10, 12])
        record_node(board, 12, neighbors=[10, 11])

        first = analyze_graph(board)
        second = analyze_graph(board)

        self.assertEqual(first.node_metrics, second.node_metrics)
        self.assertEqual(first.edge_metrics, second.edge_metrics)
        self.assertEqual(first.node_metrics[1].community_id, 0)
        self.assertEqual(first.node_metrics[10].community_id, 1)

    def test_bridge_between_communities_has_highest_edge_betweenness(self) -> None:
        board = Blackboard()
        record_node(board, 1, neighbors=[2, 3])
        record_node(board, 2, neighbors=[1, 3])
        record_node(board, 3, neighbors=[1, 2, 10])
        record_node(board, 10, neighbors=[3, 11, 12])
        record_node(board, 11, neighbors=[10, 12])
        record_node(board, 12, neighbors=[10, 11])

        analysis = analyze_graph(board)
        bridge = analysis.edge_metrics[(3, 10)]

        self.assertTrue(bridge.cross_community)
        self.assertEqual(bridge.edge_betweenness, 1.0)
        self.assertGreater(bridge.edge_betweenness, analysis.edge_metrics[(1, 2)].edge_betweenness)


if __name__ == "__main__":
    unittest.main()

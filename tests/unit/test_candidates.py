import unittest
from types import SimpleNamespace

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.candidates import (
    Candidate,
    generate_candidates,
    parse_llm_batch,
    select_deterministic_batch,
)
from starnet.policy.graph_analysis import EdgeMetrics, NodeMetrics


def node_metrics(*, positive: float = 0.0, danger: float = 0.0) -> NodeMetrics:
    return NodeMetrics(
        degree=0.0,
        pagerank=0.0,
        core=0.0,
        betweenness=0.0,
        voterank=0.0,
        influence=0.0,
        positive_influence=positive,
        danger=danger,
        community_id=0,
    )


def analysis(
    metrics: dict[int, NodeMetrics], edges: dict[tuple[int, int], EdgeMetrics] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(node_metrics=metrics, edge_metrics=edges or {})


class CandidateGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.board = Blackboard()

    def _scan(self, node_id: int, *, w: float, persona: str, comm_left: int, neighbors: list[int]) -> None:
        self.board.record_scan(
            node_id,
            {"w": w, "persona": persona, "comm_left": comm_left, "neighbors": neighbors},
        )

    def test_high_risk_violent_node_is_p0_and_hides_lower_priorities(self) -> None:
        self._scan(1, w=-5, persona="暴力", comm_left=3, neighbors=[2])
        self._scan(2, w=2, persona="和平", comm_left=3, neighbors=[1])
        graph = analysis(
            {1: node_metrics(danger=0.8), 2: node_metrics(positive=0.9)},
            {(1, 2): EdgeMetrics(0.9, True, 0.9)},
        )

        candidates = generate_candidates(graph, self.board, budget=10.0)

        self.assertEqual([candidate.candidate_id for candidate in candidates], ["shield:1"])

    def test_cross_community_negative_bridge_generates_cut(self) -> None:
        self._scan(1, w=-3, persona="暴力", comm_left=3, neighbors=[2])
        self._scan(2, w=2, persona="中立", comm_left=3, neighbors=[1])
        graph = analysis(
            {1: node_metrics(danger=0.4), 2: node_metrics(positive=0.5)},
            {(1, 2): EdgeMetrics(0.7, True, 0.5)},
        )

        candidates = generate_candidates(graph, self.board, budget=5.0)

        self.assertEqual([candidate.candidate_id for candidate in candidates], ["cut:1-2", "comm:2:1"])

    def test_communication_requires_positive_nonviolent_node_quota_and_budget(self) -> None:
        self._scan(1, w=1, persona="和平", comm_left=1, neighbors=[])
        self._scan(2, w=1, persona="和平", comm_left=0, neighbors=[])
        self._scan(3, w=1, persona="暴力", comm_left=3, neighbors=[])
        graph = analysis(
            {
                1: node_metrics(positive=0.8),
                2: node_metrics(positive=0.9),
                3: node_metrics(positive=1.0),
            }
        )

        self.assertEqual(
            [candidate.candidate_id for candidate in generate_candidates(graph, self.board, budget=2.0)],
            ["comm:1:1"],
        )
        self.assertEqual(generate_candidates(graph, self.board, budget=1.99), [])


class BatchSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shield = Candidate("shield:1", Action("shield", 1), 0, 0.9, 0.18, "shield")
        self.cut = Candidate("cut:1-2", Action("cut", 1, 2), 1, 0.8, 0.26, "cut")
        self.comm = Candidate("comm:3:1", Action("comm", 3, prompt_id=1), 2, 0.6, 0.3, "comm")
        self.candidates = {candidate.candidate_id: candidate for candidate in (self.shield, self.cut, self.comm)}

    def test_deterministic_batch_respects_cost_and_shield_cut_conflict(self) -> None:
        self.assertEqual(select_deterministic_batch(self.candidates.values(), 7.0), ["shield:1", "comm:3:1"])
        self.assertEqual(select_deterministic_batch(self.candidates.values(), 4.0), ["cut:1-2"])

    def test_llm_parser_filters_invalid_entries_and_uses_fallback_when_empty(self) -> None:
        self.assertEqual(
            parse_llm_batch(
                '{"mode": "balanced", "candidate_ids": ["unknown", "shield:1", "cut:1-2", "shield:1", "comm:3:1"]}',
                self.candidates,
                7.0,
            ),
            ["shield:1", "comm:3:1"],
        )
        self.assertEqual(
            parse_llm_batch("not json", self.candidates, 7.0),
            ["shield:1", "comm:3:1"],
        )


if __name__ == "__main__":
    unittest.main()

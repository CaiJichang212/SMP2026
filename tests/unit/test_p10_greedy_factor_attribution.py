from __future__ import annotations

import unittest

from scripts.run_p10_greedy_factor_attribution import generate_candidates
from starnet.model.blackboard import Blackboard


def board() -> Blackboard:
    result = Blackboard(node_count=3)
    weights = {1: -10.0, 2: -20.0, 3: 100.0}
    for node_id in (1, 2, 3):
        result.record_scan(node_id, {
            "w": weights[node_id],
            "persona": "暴力" if node_id < 3 else "和平",
            "comm_left": 3,
            "neighbors": [other for other in (1, 2, 3) if other != node_id],
        })
    return result


class P10GreedyFactorTests(unittest.TestCase):
    def test_narrow_arm_restores_only_the_positive_negative_negative_cut(self) -> None:
        current = generate_candidates(board(), 100.0, {}, "fixed__full_gate")
        narrow = generate_candidates(
            board(), 100.0, {}, "fixed__full_gate_plus_negative_negative_cut",
        )
        current_ids = {candidate.candidate_id for candidate in current}
        added = [candidate for candidate in narrow if candidate.candidate_id not in current_ids]
        self.assertEqual([candidate.candidate_id for candidate in added], ["cut:1-2"])
        self.assertGreater(added[0].score, 0.0)

    def test_persona_prior_changes_scores_without_enumerating_structure(self) -> None:
        fixed = generate_candidates(board(), 100.0, {}, "fixed__unrestricted")
        persona = generate_candidates(board(), 100.0, {}, "persona__unrestricted")
        fixed_actions = {candidate.action for candidate in fixed}
        persona_actions = {candidate.action for candidate in persona}
        self.assertEqual(fixed_actions, persona_actions)
        fixed_scores = {candidate.candidate_id: candidate.score for candidate in fixed}
        persona_scores = {candidate.candidate_id: candidate.score for candidate in persona}
        self.assertNotEqual(fixed_scores["comm:1:1"], persona_scores["comm:1:1"])


if __name__ == "__main__":
    unittest.main()

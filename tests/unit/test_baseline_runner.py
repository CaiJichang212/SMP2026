"""本地 OpenAI 兼容运行器的脱敏诊断辅助函数测试。"""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from scripts.run_baseline_openai import default_step_limit, seed_budget, seed_snapshot_matches


class BaselineRunnerTests(unittest.TestCase):
    def test_seed_budget_requires_numeric_max_budget(self) -> None:
        self.assertEqual(seed_budget({"global_setting": {"max_budget": 20}}), 20.0)
        self.assertIsNone(seed_budget({"global_setting": {"max_budget": "20"}}))

    def test_default_step_limit_reaches_beyond_full_competition_scan(self) -> None:
        self.assertEqual(default_step_limit(50, 100.0), 102)
        self.assertEqual(default_step_limit(100, 200.0), 202)

    def test_seed_snapshot_requires_all_scanned_nodes_and_edges_to_match(self) -> None:
        seed = {
            "nodes": [
                {"id": 1, "w": -1.0, "persona": "暴力", "comm_left": 3},
                {"id": 2, "w": 2.0, "persona": "和平", "comm_left": 1},
            ],
            "edges": [[1, 2]],
        }
        nodes = {
            1: SimpleNamespace(w=-1.0, persona="暴力", comm_left=3),
            2: SimpleNamespace(w=2.0, persona="和平", comm_left=1),
        }

        self.assertTrue(seed_snapshot_matches(seed, nodes, {(1, 2)}))
        self.assertFalse(seed_snapshot_matches(seed, nodes, set()))

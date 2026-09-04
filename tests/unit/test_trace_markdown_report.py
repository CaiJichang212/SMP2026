"""Regression tests for the JSONL-to-Markdown trace report command."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "render_trace_markdown.py"


def record(event: str, *, seq: int, step: int, state: str, data: dict[str, object], budget: float) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": "run-123",
        "seed_id": "small-network",
        "seq": seq,
        "timestamp": f"2026-09-04T02:55:{seq:02d}.000Z",
        "event": event,
        "step": step,
        "state": state,
        "budget_before": budget,
        "budget_after": budget,
        "data": data,
    }


class TraceMarkdownReportTests(unittest.TestCase):
    def test_cli_writes_readable_summary_for_schema_v1_trace(self) -> None:
        records = [
            record(
                "run.started",
                seq=1,
                step=0,
                state="INIT",
                budget=10.0,
                data={"node_count": 2, "max_llm_calls": 3},
            ),
            record(
                "analysis.completed",
                seq=2,
                step=1,
                state="ANALYZE",
                budget=10.0,
                data={"phase": "analyze", "node_count": 2, "edge_count": 1, "community_count": 1},
            ),
            record(
                "candidates.generated",
                seq=3,
                step=1,
                state="ANALYZE",
                budget=10.0,
                data={
                    "filtered_count": 1,
                    "candidates": [{"candidate_id": "shield:2", "score": 0.965}],
                },
            ),
            record(
                "llm.completed",
                seq=4,
                step=1,
                state="PLAN_BATCH",
                budget=10.0,
                data={
                    "llm_calls": 1,
                    "parsed": {"accepted": True, "candidate_ids": ["shield:2"]},
                    "raw_output": {"reason": "high risk"},
                },
            ),
            record(
                "plan.created",
                seq=5,
                step=1,
                state="PLAN_BATCH",
                budget=10.0,
                data={"source": "llm", "selected_candidate_ids": ["shield:2"], "fallback_reason": None},
            ),
            record(
                "action.completed",
                seq=6,
                step=1,
                state="EXECUTE",
                budget=5.0,
                data={
                    "success": True,
                    "action": {"kind": "shield", "target_node_1": 2, "target_node_2": None, "prompt_id": None},
                    "blackboard_delta": {"added_dead_nodes": [2], "removed_edges": [[1, 2]]},
                },
            ),
            record(
                "run.stopped",
                seq=7,
                step=2,
                state="STOP",
                budget=5.0,
                data={
                    "reason": "no_valid_actions",
                    "action_attempts": 1,
                    "action_successes": 1,
                    "action_failures": 0,
                    "llm_calls": 1,
                    "remaining_budget": 5.0,
                    "blackboard": {
                        "dead_nodes": [2],
                        "edges": [],
                        "nodes": {"1": {"persona": "和平", "w": 10.0, "comm_left": 3}},
                    },
                },
            ),
            record(
                "evaluation.completed",
                seq=8,
                step=2,
                state="STOP",
                budget=5.0,
                data={"score": 42.5, "remaining_budget": 5.0, "stop_reason": "no_valid_actions"},
            ),
        ]
        records[5]["budget_before"] = 10.0

        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source = directory / "trace.jsonl"
            output = directory / "report.md"
            source.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(source), "--output", str(output)],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = output.read_text(encoding="utf-8")

        self.assertIn("# StarNet 运行轨迹报告", report)
        self.assertIn("隔离节点 2", report)
        self.assertIn("shield:2", report)
        self.assertIn("42.5", report)
        self.assertIn("最终网络状态", report)
        self.assertIn("动作汇总：隔离节点 1 次。", report)

    def test_cli_rejects_invalid_json_with_line_number(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "invalid.jsonl"
            source.write_text("{not json}\n", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(source)],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("第 1 行不是合法 JSON", completed.stderr)


if __name__ == "__main__":
    unittest.main()

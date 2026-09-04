"""Structured runtime trace regression tests using only public environment calls."""

from __future__ import annotations

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from starnet.runtime.controller import RuntimeController
from starnet.runtime.trace import ConsoleTraceSink, JsonlTraceSink, RuntimeTrace, safe_json_value


class TraceEnvironment:
    def __init__(self, *, budget: float = 20.0, reject_communication: bool = False) -> None:
        self.budget = budget
        self.reject_communication = reject_communication
        self.calls: list[tuple[object, ...]] = []
        self.nodes = {
            1: {"w": 10.0, "persona": "和平", "comm_left": 3, "neighbors": [2, 4]},
            2: {"w": -40.0, "persona": "暴力", "comm_left": 3, "neighbors": [1, 3]},
            3: {"w": 0.0, "persona": "中立", "comm_left": 3, "neighbors": [2, 4]},
            4: {"w": 15.0, "persona": "和平", "comm_left": 3, "neighbors": [1, 3]},
        }
        self.edges = {(1, 2), (2, 3), (3, 4), (1, 4)}

    def get_remaining_budget(self) -> float:
        return self.budget

    def scan_node(self, node_id: int) -> dict[str, object] | None:
        self.calls.append(("scan", node_id))
        if self.budget < 0.5 or node_id not in self.nodes:
            return None
        self.budget -= 0.5
        return dict(self.nodes[node_id])

    def communicate(self, node_id: int, prompt_id: int) -> dict[str, object]:
        self.calls.append(("comm", node_id, prompt_id))
        if self.budget < 2.0:
            return {"status": "budget_exhausted"}
        self.budget -= 2.0
        if self.reject_communication:
            return {"status": "max_comm_reached"}
        self.nodes[node_id]["w"] = float(self.nodes[node_id]["w"]) + 1.0
        self.nodes[node_id]["comm_left"] = int(self.nodes[node_id]["comm_left"]) - 1
        return {"status": "success", "new_w": self.nodes[node_id]["w"]}

    def cut_link(self, left: int, right: int) -> bool:
        self.calls.append(("cut", left, right))
        edge = (left, right) if left < right else (right, left)
        if self.budget < 3.0 or edge not in self.edges:
            return False
        self.budget -= 3.0
        self.edges.remove(edge)
        return True

    def shield_node(self, node_id: int) -> bool:
        self.calls.append(("shield", node_id))
        if self.budget < 5.0 or node_id not in self.nodes:
            return False
        self.budget -= 5.0
        del self.nodes[node_id]
        self.edges = {edge for edge in self.edges if node_id not in edge}
        return True


class MemorySink:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def emit(self, record: dict[str, object]) -> None:
        self.records.append(record)


class RaisingSink:
    def emit(self, record: dict[str, object]) -> None:
        raise RuntimeError("diagnostic sink failure")


def run_to_first_intervention(controller: RuntimeController) -> None:
    for _ in range(5):
        controller.step()


class RuntimeTraceTests(unittest.TestCase):
    def test_jsonl_records_have_complete_envelope_and_scan_accounting(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            trace_file = Path(temporary_directory) / "trace.jsonl"
            environment = TraceEnvironment(budget=10.0)
            environment.nodes = {
                1: {"w": 2.0, "persona": "暴力", "comm_left": 3, "neighbors": []}
            }
            environment.edges = set()
            controller = RuntimeController(environment, node_count=1)
            trace = RuntimeTrace(
                run_id="run-1",
                seed_id="seed-1",
                sinks=[JsonlTraceSink(trace_file)],
            )
            controller.attach_trace(trace)
            self.assertEqual(controller.step(), 0)
            self.assertEqual(controller.step(), 1)
            controller.record_evaluation(7.5, budget_before=environment.budget)
            trace.close()

            records = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(records)
        required = {
            "schema_version",
            "run_id",
            "seed_id",
            "seq",
            "timestamp",
            "event",
            "step",
            "state",
            "budget_before",
            "budget_after",
            "data",
        }
        self.assertTrue(all(required.issubset(record) for record in records))
        self.assertEqual([record["seq"] for record in records], list(range(1, len(records) + 1)))
        self.assertTrue(all(str(record["timestamp"]).endswith("Z") for record in records))
        self.assertTrue(all(record["run_id"] == "run-1" for record in records))

        action = next(record for record in records if record["event"] == "action.completed")
        self.assertEqual(action["budget_before"], 10.0)
        self.assertEqual(action["budget_after"], 9.5)
        self.assertIn("1", action["data"]["blackboard_delta"]["added_nodes"])
        scan_completed = next(record for record in records if record["event"] == "scan.completed")
        self.assertEqual(scan_completed["data"]["blackboard"]["nodes"]["1"]["persona"], "暴力")
        self.assertEqual(records[-1]["event"], "evaluation.completed")
        self.assertIn("run.stopped", {record["event"] for record in records})

    def test_state_machine_analysis_candidates_llm_and_reanalysis_are_traceable(self) -> None:
        environment = TraceEnvironment()
        sink = MemorySink()
        controller = RuntimeController(
            environment,
            lambda _: {"mode": "risk_first", "candidate_ids": ["shield:2"]},
            node_count=4,
        )
        controller.attach_trace(RuntimeTrace(run_id="run", seed_id="seed", sinks=[sink]))
        run_to_first_intervention(controller)

        events = [str(record["event"]) for record in sink.records]
        transitions = [
            record["data"]["new_state"]
            for record in sink.records
            if record["event"] == "state.transition"
        ]
        self.assertIn("analysis.completed", events)
        self.assertIn("candidates.generated", events)
        self.assertIn("llm.requested", events)
        self.assertIn("llm.completed", events)
        self.assertIn("plan.created", events)
        self.assertIn("queue.revalidated", events)
        self.assertIn("REANALYZE", transitions)
        self.assertEqual(transitions[:4], ["SCAN_ALL", "ANALYZE", "PLAN_BATCH", "EXECUTE"])
        plan = next(record for record in sink.records if record["event"] == "plan.created")
        self.assertEqual(plan["data"]["source"], "llm")
        self.assertEqual(plan["data"]["selected_candidate_ids"], ["shield:2"])

    def test_llm_fallback_reasons_and_quota_are_observable(self) -> None:
        cases: list[tuple[object, str, str]] = [
            ("not valid json", "deterministic_fallback", "invalid_json"),
            ({"mode": "risk_first", "candidate_ids": ["missing"]}, "deterministic_fallback", "unknown_candidate"),
            ({"mode": "risk_first", "candidate_ids": []}, "deterministic_fallback", "empty_selection"),
        ]
        for response, source, reason in cases:
            with self.subTest(reason=reason):
                sink = MemorySink()
                controller = RuntimeController(TraceEnvironment(), lambda _: response, node_count=4)
                controller.attach_trace(RuntimeTrace(run_id="run", seed_id="seed", sinks=[sink]))
                run_to_first_intervention(controller)
                plan = next(record for record in sink.records if record["event"] == "plan.created")
                failure = next(record for record in sink.records if record["event"] == "llm.failed")
                self.assertEqual(plan["data"]["source"], source)
                self.assertEqual(failure["data"]["fallback_reason"], reason)

        sink = MemorySink()
        controller = RuntimeController(TraceEnvironment(), lambda _: {"mode": "risk_first", "candidate_ids": []}, node_count=4)
        controller.commander.llm_calls = 3
        controller.attach_trace(RuntimeTrace(run_id="run", seed_id="seed", sinks=[sink]))
        run_to_first_intervention(controller)
        quota_failure = next(record for record in sink.records if record["event"] == "llm.failed")
        self.assertEqual(quota_failure["data"]["source"], "quota_exhausted")
        self.assertEqual(quota_failure["data"]["fallback_reason"], "quota_exhausted")

        sink = MemorySink()

        def broken_ranker(_: dict[str, object]) -> object:
            raise TimeoutError("request token=top-secret timed out")

        controller = RuntimeController(TraceEnvironment(), broken_ranker, node_count=4)
        controller.attach_trace(RuntimeTrace(run_id="run", seed_id="seed", sinks=[sink]))
        run_to_first_intervention(controller)
        failure = next(record for record in sink.records if record["event"] == "llm.failed")
        self.assertEqual(failure["data"]["fallback_reason"], "exception")
        self.assertEqual(failure["data"]["error"]["type"], "TimeoutError")
        self.assertNotIn("top-secret", failure["data"]["error"]["message"])

    def test_action_failure_keeps_raw_response_and_does_not_fabricate_weight(self) -> None:
        environment = TraceEnvironment(reject_communication=True)
        environment.nodes[2]["persona"] = "和平"
        environment.nodes[2]["w"] = 1.0
        sink = MemorySink()
        controller = RuntimeController(
            environment,
            lambda _: {"mode": "growth_first", "candidate_ids": ["comm:1:1"]},
            node_count=4,
        )
        controller.attach_trace(RuntimeTrace(run_id="run", seed_id="seed", sinks=[sink]))
        run_to_first_intervention(controller)

        failure = next(record for record in sink.records if record["event"] == "action.failed")
        self.assertEqual(failure["data"]["raw_response"], {"status": "max_comm_reached"})
        self.assertFalse(failure["data"]["success"])
        updated = failure["data"]["blackboard_delta"]["updated_nodes"]
        self.assertEqual(updated["1"]["after"]["comm_left"], 0)
        self.assertEqual(updated["1"]["after"]["w"], 10.0)
        self.assertEqual(controller.blackboard.nodes[1].w, 10.0)

    def test_broken_sink_and_disabled_trace_leave_policy_results_identical(self) -> None:
        baseline_environment = TraceEnvironment()
        traced_environment = TraceEnvironment()
        baseline = RuntimeController(baseline_environment, node_count=4)
        traced = RuntimeController(traced_environment, node_count=4)
        traced.attach_trace(RuntimeTrace(run_id="run", seed_id="seed", sinks=[RaisingSink()]))

        for _ in range(4):
            baseline.step()
            traced.step()

        self.assertEqual(baseline_environment.calls, traced_environment.calls)
        self.assertEqual(baseline_environment.budget, traced_environment.budget)
        self.assertEqual(baseline.blackboard.snapshot(), traced.blackboard.snapshot())
        self.assertEqual(baseline.llm_calls, traced.llm_calls)

    def test_console_sink_prints_one_compact_line_per_outer_step(self) -> None:
        stream = io.StringIO()
        environment = TraceEnvironment()
        controller = RuntimeController(environment, node_count=4)
        controller.attach_trace(
            RuntimeTrace(run_id="run", seed_id="seed", sinks=[ConsoleTraceSink(stream)])
        )
        controller.step()
        controller.step()
        self.assertEqual(len(stream.getvalue().splitlines()), 2)

    def test_safe_json_value_redacts_credentials_and_headers(self) -> None:
        value = safe_json_value(
            {
                "api-key": "secret-value",
                "headers": {"Authorization": "Bearer secret-value"},
                "error": "token=secret-value Bearer secret-value",
            }
        )
        self.assertEqual(value["api-key"], "[REDACTED]")
        self.assertEqual(value["headers"], "[REDACTED]")
        self.assertNotIn("secret-value", value["error"])


if __name__ == "__main__":
    unittest.main()

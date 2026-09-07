#!/usr/bin/env python3
"""Run the P3 gate-closed negative-control audit on deterministic local seeds.

This is intentionally not a performance claim for adaptive exploration.  It
checks the safety invariant required before a scenario profile is qualified:
unverified B5 variants must be exactly the B1 action trace and must not spend
LLM calls.  The synthetic environment exposes only the same public methods
used by the controller and uses the generated seed payload as its fixture.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from starnet.experiments.seeds import matrix_seed_payloads
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.config import LLMMode, PolicyConfig, PolicyMode
from starnet.runtime.controller import RuntimeController


class PublicFixtureEnvironment:
    def __init__(self, seed: dict[str, Any]) -> None:
        self.budget = float(seed["global_setting"]["max_budget"])
        self.prompts = {int(key): float(value) for key, value in seed["prompts"].items()}
        self.nodes = {
            int(node["id"]): {
                "w": float(node["w"]),
                "persona": str(node["persona"]),
                "comm_left": int(node["comm_left"]),
            }
            for node in seed["nodes"]
        }
        self.edges = {tuple(sorted((int(left), int(right)))) for left, right in seed["edges"]}
        self.calls: list[tuple[Any, ...]] = []

    def get_remaining_budget(self) -> float:
        return self.budget

    def _neighbors(self, node_id: int) -> list[int]:
        return sorted(right if left == node_id else left for left, right in self.edges if node_id in (left, right))

    def scan_node(self, node_id: int) -> dict[str, Any] | None:
        self.calls.append(("scan", node_id))
        if node_id not in self.nodes or self.budget < 0.5:
            return None
        self.budget -= 0.5
        node = self.nodes[node_id]
        return {**node, "neighbors": self._neighbors(node_id)}

    def communicate(self, node_id: int, prompt_id: int) -> dict[str, Any]:
        self.calls.append(("comm", node_id, prompt_id))
        if node_id not in self.nodes or self.budget < 2.0:
            return {"status": "budget_exhausted"}
        node = self.nodes[node_id]
        if node["comm_left"] <= 0:
            return {"status": "max_comm_reached"}
        self.budget -= 2.0
        turn = 4 - int(node["comm_left"])
        node["w"] += self.prompts[prompt_id] / (2 ** turn)
        node["comm_left"] -= 1
        return {"status": "success", "new_w": node["w"]}

    def cut_link(self, left: int, right: int) -> bool:
        self.calls.append(("cut", left, right))
        edge = tuple(sorted((left, right)))
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


def _configs() -> dict[str, PolicyConfig]:
    return {
        "b1_persuasion": PolicyConfig(
            policy_mode=PolicyMode.B1_PERSUASION,
            enable_shield=False,
            enable_cut=False,
            max_llm_calls=0,
        ),
        "b5_adaptive": PolicyConfig(policy_mode=PolicyMode.B5_ADAPTIVE, max_llm_calls=0),
        "b5_step_llm": PolicyConfig(policy_mode=PolicyMode.B5_ADAPTIVE, llm_schedule=LLMMode.STEP, max_llm_calls=5),
        "b5_event_llm": PolicyConfig(policy_mode=PolicyMode.B5_ADAPTIVE, llm_schedule=LLMMode.EVENT, max_llm_calls=5),
    }


def run_audit() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seeds = matrix_seed_payloads(repetitions=3)
    configs = _configs()
    for seed_id, seed in sorted(seeds.items()):
        for variant, config in configs.items():
            env = PublicFixtureEnvironment(seed)
            llm_payloads: list[dict[str, Any]] = []

            def ranker(payload: dict[str, Any]) -> dict[str, Any]:
                llm_payloads.append(payload)
                raise AssertionError("unverified P3 variant attempted an LLM call")

            controller = RuntimeController(
                env,
                ranker,
                initial_budget=env.get_remaining_budget(),
                node_count=len(seed["nodes"]),
                config=config,
                calibration_profile=DEFAULT_CALIBRATION_PROFILE,
            )
            for _ in range(500):
                if controller.stopped:
                    break
                controller.step()
            rows.append({
                "seed_id": seed_id,
                "variant": variant,
                "action_trace": env.calls,
                "remaining_budget": env.budget,
                "llm_calls": controller.llm_calls,
                "ranker_payloads": len(llm_payloads),
                "action_failures": controller.action_failures,
                "stop_reason": controller.stop_reason.value if controller.stop_reason else None,
                "effective_policy_mode": controller.effective_policy_mode.value,
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    rows = run_audit()
    args.raw.parent.mkdir(parents=True, exist_ok=True)
    args.raw.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    by_seed: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_seed.setdefault(row["seed_id"], {})[row["variant"]] = row
    trace_equal = all(
        len(set(json.dumps(by_seed[seed_id][variant]["action_trace"], sort_keys=True) for variant in _configs())) == 1
        for seed_id in by_seed
    )
    report = {
        "schema_version": 1,
        "experiment": "p3-gate-closed-negative-control",
        "sessions": len(rows),
        "seed_blocks": len(by_seed),
        "variants": sorted(_configs()),
        "all_action_traces_equal": trace_equal,
        "max_llm_calls": max(row["llm_calls"] for row in rows),
        "max_ranker_payloads": max(row["ranker_payloads"] for row in rows),
        "action_failures": sum(row["action_failures"] for row in rows),
        "effective_modes": sorted({row["effective_policy_mode"] for row in rows}),
        "gate_passed": bool(trace_equal and report_safe(rows)),
        "interpretation": "This qualifies fail-closed behavior only; it is not evidence of adaptive exploration gain.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["gate_passed"] else 2


def report_safe(rows: list[dict[str, Any]]) -> bool:
    return all(row["llm_calls"] == 0 and row["ranker_payloads"] == 0 and row["action_failures"] == 0 for row in rows)


if __name__ == "__main__":
    raise SystemExit(main())

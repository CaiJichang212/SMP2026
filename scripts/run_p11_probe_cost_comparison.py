#!/usr/bin/env python3
"""Compare one-node and verified two-node prompt calibration costs."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p11_prompt_calibration import (
    _apply, digest, json_digest, prompt_configs,
)
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action
from starnet.policy.budget_experiment import communication_tail
from starnet.policy.cmg import PredictiveState
from starnet.policy.prompt_calibration_experiment import (
    PromptCalibrationLedger, select_prompt_probe_nodes,
)
from starnet.runtime.env_adapter import apply_action_outcome


PROTOCOL = ROOT / "experiments/manifests/p11-single-vs-double-probe-20260914.json"


def run_arm(seed, *, probe_nodes: int, calibrated: bool):
    env = LocalPublicEnvironment(seed)
    board = Blackboard(node_count=50)
    for node_id in range(1, 51):
        action = Action("scan", node_id)
        if not apply_action_outcome(env, board, action, env.get_remaining_budget()).succeeded:
            raise RuntimeError("P11 probe-cost scan failed")
    nodes = select_prompt_probe_nodes(
        board, max_probe_budget=6.0 * probe_nodes, max_nodes=probe_nodes,
    )
    ledger = PromptCalibrationLedger(required_complete_nodes=probe_nodes)
    for node_id in nodes:
        for prompt_id in (1, 2, 3):
            old, new, turn = _apply(env, board, Action("comm", node_id, prompt_id=prompt_id))
            ledger.observe_success(node_id, prompt_id, turn, old, new)
    schedule = communication_tail(
        PredictiveState.from_blackboard(board), env.get_remaining_budget(),
        lambda node_id, node, turn: 12.75 * (0.5 ** (turn - 1)),
        remaining_steps=117 - 50 - 3 * len(nodes),
    ).actions
    prompt_id = ledger.best_or_default() if calibrated else 1
    targets = []
    for planned in schedule:
        _apply(env, board, Action("comm", planned.target_node_1, prompt_id=prompt_id))
        targets.append(planned.target_node_1)
    return {
        "score": env.evaluate(), "prompt_id": prompt_id,
        "probe_nodes": list(nodes), "probe_budget": 6.0 * len(nodes),
        "continuation_actions": len(targets),
        "continuation_target_sha256": json_digest(targets),
        "calibrated_prompt_id": ledger.calibrated_prompt_id,
        "provisional_prompt_ids": list(ledger.provisional_prompt_ids),
        "confident": ledger.confident, "calibration_complete": ledger.calibration_complete,
        "censored": ledger.censored, "failures": ledger.failures,
    }


def metric(rows, left, right):
    values = [row["arms"][left]["score"] - row["arms"][right]["score"] for row in rows]
    return {
        "cases": len(values), "mean": statistics.fmean(values),
        "minimum": min(values), "maximum": max(values),
        "win_tie_loss": [sum(value > 1e-8 for value in values),
                         sum(abs(value) <= 1e-8 for value in values),
                         sum(value < -1e-8 for value in values)],
        "losses": [{"family": row["family"], "prompt_config": row["prompt_config"],
                    "delta": value} for row, value in zip(rows, values) if value < -1e-8],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = {
        "protocol_sha256": digest(PROTOCOL), "runner_sha256": digest(Path(__file__)),
        "ledger_sha256": digest(ROOT / "src/starnet/policy/prompt_calibration_experiment.py"),
        "families": list(SEED_SPECS), "prompt_configs": [name for name, _ in prompt_configs()],
        "cases": 72, "workers": 1,
    }
    progress = args.output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("P11 probe-cost progress identity mismatch")
        rows = list(saved.get("rows", []))
    completed = {(row["family"], row["prompt_config"]) for row in rows}
    for family in SEED_SPECS:
        original = seed_payload(family, 50, 1)
        for name, values in prompt_configs():
            if (family, name) in completed:
                continue
            seed = copy.deepcopy(original)
            seed["prompts"] = {str(index): values[index - 1] for index in (1, 2, 3)}
            arms = {
                "single_calibrated": run_arm(seed, probe_nodes=1, calibrated=True),
                "single_fixed": run_arm(seed, probe_nodes=1, calibrated=False),
                "double_calibrated": run_arm(seed, probe_nodes=2, calibrated=True),
                "double_fixed": run_arm(seed, probe_nodes=2, calibrated=False),
            }
            if (arms["single_calibrated"]["continuation_target_sha256"]
                    != arms["single_fixed"]["continuation_target_sha256"]
                    or arms["double_calibrated"]["continuation_target_sha256"]
                    != arms["double_fixed"]["continuation_target_sha256"]):
                raise RuntimeError("equal-cost continuation schedule mismatch")
            truth = max((1, 2, 3), key=lambda prompt_id: values[prompt_id - 1])
            rows.append({"family": family, "prompt_config": name,
                         "seed_sha256": json_digest(seed), "true_best_prompt_id": truth,
                         "arms": arms})
            completed.add((family, name))
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps({"config": config, "rows": rows},
                                           ensure_ascii=False, indent=2) + "\n")
    if len(rows) != 72:
        raise ValueError("P11 probe-cost cohort incomplete")
    report = {
        "config": config, "complete": True,
        "accuracy": {
            arm: sum(row["arms"][arm]["prompt_id"] == row["true_best_prompt_id"]
                     for row in rows) / len(rows)
            for arm in ("single_calibrated", "double_calibrated")
        },
        "comparisons": {
            "single_calibrated_vs_fixed": metric(rows, "single_calibrated", "single_fixed"),
            "double_calibrated_vs_fixed": metric(rows, "double_calibrated", "double_fixed"),
            "single_vs_double_calibrated": metric(rows, "single_calibrated", "double_calibrated"),
        },
        "rows": rows, "changes_runtime_selection": False,
        "production_enabled": False, "platform_score": None,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"accuracy": report["accuracy"],
                      "comparisons": report["comparisons"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

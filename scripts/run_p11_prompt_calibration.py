#!/usr/bin/env python3
"""Evaluate public prompt calibration over consumed seeds and hidden prompt maps."""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import LocalPublicEnvironment
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.budget_experiment import communication_tail
from starnet.policy.cmg import PredictiveState
from starnet.policy.prompt_calibration_experiment import (
    PromptCalibrationLedger, select_prompt_probe_nodes,
)
from starnet.runtime.env_adapter import apply_action_outcome


PROTOCOL = ROOT / "experiments/manifests/p11-public-prompt-calibration-20260914.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prompt_configs():
    configs = []
    for values in itertools.permutations((15.0, 10.0, -5.0)):
        configs.append(("base_" + "_".join(str(int(value)) for value in values), values))
    configs.extend((
        ("wide_24_7_-12", (24.0, 7.0, -12.0)),
        ("wide_-12_24_7", (-12.0, 24.0, 7.0)),
        ("wide_7_-12_24", (7.0, -12.0, 24.0)),
        ("close_6_5_4", (6.0, 5.0, 4.0)),
        ("close_4_6_5", (4.0, 6.0, 5.0)),
        ("close_5_4_6", (5.0, 4.0, 6.0)),
    ))
    return tuple(configs)


def _apply(env, board, action):
    budget = env.get_remaining_budget()
    if not is_legal_action(action, board, budget):
        raise RuntimeError("illegal P11 development action")
    old = board.nodes[action.target_node_1].w if action.kind == "comm" else None
    turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
    outcome = apply_action_outcome(env, board, action, budget)
    if not outcome.succeeded:
        raise RuntimeError("failed P11 development action")
    new = board.nodes[action.target_node_1].w if action.kind == "comm" else None
    return old, new, turn


def prepare(seed):
    env = LocalPublicEnvironment(seed)
    board = Blackboard(node_count=50)
    for node_id in range(1, 51):
        budget = env.get_remaining_budget()
        action = Action("scan", node_id)
        if not apply_action_outcome(env, board, action, budget).succeeded:
            raise RuntimeError("failed P11 scan")
    nodes = select_prompt_probe_nodes(board)
    ledger = PromptCalibrationLedger()
    for node_id in nodes:
        for prompt_id in (1, 2, 3):
            action = Action("comm", node_id, prompt_id=prompt_id)
            old, new, turn = _apply(env, board, action)
            ledger.observe_success(node_id, prompt_id, turn, old, new)
    tail = communication_tail(
        PredictiveState.from_blackboard(board), env.get_remaining_budget(),
        lambda node_id, node, turn: 12.75 * (0.5 ** (turn - 1)),
        remaining_steps=117 - 50 - 3 * len(nodes),
    )
    return env, board, ledger, nodes, tail.actions


def run_arm(seed, *, calibrated):
    env, board, ledger, nodes, schedule = prepare(seed)
    prompt_id = ledger.best_or_default() if calibrated else 1
    targets = []
    for planned in schedule:
        action = Action("comm", planned.target_node_1, prompt_id=prompt_id)
        _apply(env, board, action)
        targets.append(action.target_node_1)
    return {
        "score": env.evaluate(), "remaining_budget": env.get_remaining_budget(),
        "prompt_id": prompt_id, "probe_nodes": list(nodes),
        "probe_budget": 6.0 * len(nodes), "probe_successes": 3 * len(nodes),
        "continuation_targets": targets,
        "continuation_target_sha256": json_digest(targets),
        "calibrated_prompt_id": ledger.calibrated_prompt_id,
        "confident": ledger.confident,
        "calibration_complete": ledger.calibration_complete,
        "node_rankings": {str(key): list(value) for key, value in ledger.node_rankings().items()},
        "normalized_values": ledger.normalized_values(),
        "accepted": ledger.accepted, "censored": ledger.censored,
        "failures": ledger.failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = {
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "ledger_sha256": digest(ROOT / "src/starnet/policy/prompt_calibration_experiment.py"),
        "families": list(SEED_SPECS), "repetition": 1,
        "prompt_configs": [{"name": name, "values": list(values)}
                           for name, values in prompt_configs()],
        "cases": 72, "workers": 1,
    }
    progress = args.output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("P11 progress identity mismatch")
        rows = list(saved.get("rows", []))
    completed = {(row["family"], row["prompt_config"]) for row in rows}
    for family in SEED_SPECS:
        original = seed_payload(family, 50, 1)
        for name, values in prompt_configs():
            if (family, name) in completed:
                continue
            seed = copy.deepcopy(original)
            seed["prompts"] = {str(prompt_id): values[prompt_id - 1]
                               for prompt_id in (1, 2, 3)}
            candidate = run_arm(seed, calibrated=True)
            control = run_arm(seed, calibrated=False)
            truth = max((1, 2, 3), key=lambda prompt_id: values[prompt_id - 1])
            if candidate["continuation_target_sha256"] != control["continuation_target_sha256"]:
                raise RuntimeError("P11 continuation schedules differ")
            row = {
                "family": family, "repetition": 1, "prompt_config": name,
                "seed_sha256": json_digest(seed),
                "true_best_prompt_id": truth,
                "identified_correctly": candidate["calibrated_prompt_id"] == truth,
                "candidate": candidate, "fixed_prompt1": control,
                "delta": candidate["score"] - control["score"],
            }
            rows.append(row)
            completed.add((family, name))
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps({"config": config, "rows": rows},
                                           ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"family": family, "prompt_config": name,
                              "identified": candidate["calibrated_prompt_id"],
                              "truth": truth, "delta": row["delta"],
                              "completed": len(rows)}), flush=True)
    if len(rows) != 72:
        raise ValueError("P11 development cohort is incomplete")
    deltas = [row["delta"] for row in rows]
    report = {
        "config": config, "complete": True,
        "identification_accuracy": sum(row["identified_correctly"] for row in rows) / len(rows),
        "correct": sum(row["identified_correctly"] for row in rows),
        "confident": sum(row["candidate"]["confident"] for row in rows),
        "censored_cases": sum(bool(row["candidate"]["censored"]) for row in rows),
        "failed_probe_actions": sum(len(row["candidate"]["failures"]) for row in rows),
        "probe_budget_max": max(row["candidate"]["probe_budget"] for row in rows),
        "terminal_delta": {
            "mean": statistics.fmean(deltas), "minimum": min(deltas), "maximum": max(deltas),
            "win_tie_loss": [sum(value > 1e-8 for value in deltas),
                             sum(abs(value) <= 1e-8 for value in deltas),
                             sum(value < -1e-8 for value in deltas)],
        },
        "rows": rows, "production_enabled": False, "platform_score": None,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in (
        "identification_accuracy", "correct", "confident", "censored_cases",
        "failed_probe_actions", "probe_budget_max", "terminal_delta",
    )}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

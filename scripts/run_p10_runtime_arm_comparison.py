#!/usr/bin/env python3
"""Compare P9 and three isolated P10 runtime modes on consumed cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_submission_archives import CountingLLM
from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p10_casevo_trial import P10TrialModel
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.runtime.p8_controller import P8RuntimeController
from starnet.runtime.stage import ContestStage
from starnet.submission.starnet_model import ParticipantSquadModel


PROTOCOL = ROOT / "experiments/manifests/p10-runtime-three-arm-development-20260914.json"
RESPONSE_REPORT = ROOT / "experiments/reports/p10-gated-online-mixture-20260914.json"
ARMS = ("p9", "plan_only", "response_only", "combined")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def rank_terminal_then_first(payload):
    candidates = payload["candidates"]
    terminal = [
        candidate for candidate in candidates
        if (candidate["candidate_id"].startswith(("p10-plan:", "p8:"))
            or candidate["reason"].startswith("PG REFERENCE:"))
    ]
    item = (
        max(terminal, key=lambda candidate: (candidate["score"], candidate["candidate_id"]))
        if terminal else candidates[0]
    )
    return {
        "state_version": payload["state_version"], "mode": "single_action",
        "candidate_id": item["candidate_id"], "reason_code": "fixed_mock_ranker",
        "evidence_ids": [item["evidence_ids"][0]],
    }


def run_arm(seed, arm):
    started = time.perf_counter()
    env = LocalPublicEnvironment(seed)
    llm = CountingLLM(1.0, offline_only=True)
    people = json.loads((ROOT / "src/starnet/submission/config.json").read_text())["person"]
    if arm == "p9":
        model = ParticipantSquadModel(env, people, llm)
        model.controller = P8RuntimeController(
            env, llm_ranker=rank_terminal_then_first,
            stage=ContestStage.PRELIMINARY, config=model.controller.config,
            p8_mode="conservative",
        )
    else:
        model = P10TrialModel(env, people, llm, experiment_mode=arm)
        model.controller.commander.llm_ranker = rank_terminal_then_first
    while not model.controller.stopped:
        before = len(env.calls)
        model.step()
        if len(env.calls) - before > 1:
            raise RuntimeError("runtime arm issued multiple actions in one host step")
        if model.controller.step_number > 119:
            raise RuntimeError("runtime arm exceeded step limit")
    controller = model.controller
    actions = {kind: sum(call[0] == kind for call in env.calls)
               for kind in ("scan", "comm", "cut", "shield")}
    return {
        "score": env.evaluate(), "remaining_budget": env.get_remaining_budget(),
        "actions": actions, "action_attempts": controller.action_attempts,
        "action_failures": controller.action_failures,
        "action_sha256": json_digest(env.calls), "action_sequence": env.calls,
        "llm_calls": controller.llm_calls, "llm_accepted": controller.llm_accepted,
        "llm_fallbacks": controller.llm_fallbacks,
        "p8_planning_errors": controller.p8_planning_errors,
        "p10_searches": getattr(controller, "p10_searches", 0),
        "p10_planning_errors": getattr(controller, "p10_planning_errors", 0),
        "p10_approved_plans": getattr(controller, "p10_approved_plans", 0),
        "p10_prefix_completed": getattr(controller, "p10_prefix_completed", 0),
        "p10_prefix_failures": getattr(controller, "p10_prefix_failures", 0),
        "response_switches": getattr(controller, "p10_response_switches", 0),
        "response_disabled": getattr(controller, "p10_response_disabled", False),
        "response_disable_reason": getattr(controller, "p10_response_disable_reason", None),
        "response_activation": getattr(
            getattr(controller, "p10_response_estimator", None), "activation", None,
        ),
        "seconds": time.perf_counter() - started,
    }


def first_divergence(left, right):
    width = max(len(left), len(right))
    for index in range(width):
        first = left[index] if index < len(left) else None
        second = right[index] if index < len(right) else None
        if first != second:
            return {"action_index": index + 1, "candidate": first, "p9": second}
    return None


def metric(rows, arm):
    values = [row["arms"][arm]["score"] - row["arms"]["p9"]["score"] for row in rows]
    return {
        "cases": len(values), "mean": statistics.fmean(values),
        "minimum": min(values), "maximum": max(values),
        "win_tie_loss": [sum(value > 1e-8 for value in values),
                         sum(abs(value) <= 1e-8 for value in values),
                         sum(value < -1e-8 for value in values)],
    }


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    response = json.loads(RESPONSE_REPORT.read_text())
    legacy_key = "gated_vs_fixed:gated__unrestricted:fixed__unrestricted"
    legacy = response["by_stratum"]["legacy_independent"][legacy_key]
    if (response.get("complete") is not True or legacy["cases"] != 6
            or abs(legacy["mean"]) > 1e-8 or legacy["minimum"] < -1e-8):
        raise RuntimeError("frozen 18-case response evidence failed its legacy gate")
    config = {
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "response_report_sha256": digest(RESPONSE_REPORT),
        "arms": list(ARMS), "families": list(SEED_SPECS),
        "repetition": 1, "worker_limit": 1,
    }
    progress = args.raw_output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("runtime comparison progress identity mismatch")
        rows = list(saved.get("rows", []))
    completed = {row["family"] for row in rows}
    for family in SEED_SPECS:
        if family in completed:
            continue
        seed = seed_payload(family, 50, 1)
        arms = {arm: run_arm(seed, arm) for arm in ARMS}
        rows.append({
            "family": family, "repetition": 1,
            "seed_sha256": json_digest(seed), "arms": arms,
            "first_divergence": {
                arm: first_divergence(arms[arm]["action_sequence"], arms["p9"]["action_sequence"])
                for arm in ARMS if arm != "p9"
            },
        })
        write_json(progress, {"config": config, "rows": rows})
        print(json.dumps({
            "family": family,
            "scores": {arm: arms[arm]["score"] for arm in ARMS},
            "completed": len(rows),
        }), flush=True)
    raw = {"config": config, "complete": len(rows) == 6, "rows": rows}
    write_json(args.raw_output, raw)
    compact = {
        "config": config, "complete": raw["complete"],
        "raw_log": {"path": str(args.raw_output.resolve().relative_to(ROOT)),
                    "sha256": digest(args.raw_output), "committed": False},
        "existing_response_evidence": {
            "cases": 18, "report_sha256": digest(RESPONSE_REPORT),
            "legacy_gated_vs_fixed": legacy,
        },
        "metrics_vs_p9": {arm: metric(rows, arm) for arm in ARMS if arm != "p9"},
        "rows": [{
            "family": row["family"], "repetition": 1,
            "seed_sha256": row["seed_sha256"],
            "first_divergence": row["first_divergence"],
            "arms": {arm: {key: value for key, value in result.items()
                           if key != "action_sequence"}
                     for arm, result in row["arms"].items()},
        } for row in rows],
        "confirmation_opened": False, "production_enabled": False,
    }
    write_json(args.output, compact)
    print(json.dumps(compact["metrics_vs_p9"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run paired P8 candidates on declared development seeds only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import LocalPublicEnvironment, run_variant
from starnet.experiments.p8_seeds import (
    CONFIRMATION_REPETITIONS, DEVELOPMENT_REPETITIONS, FAMILIES, OLD_FAMILIES, R_STRATA, seed_payload,
)
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.p8_experiment import EvaluationCache, P8Mode, choose_p8_action, public_board_salt
from starnet.runtime.env_adapter import apply_action_outcome


VARIANTS: tuple[P8Mode, ...] = ("expected", "conservative", "audited")


def _action_payload(action: Action) -> dict[str, Any]:
    return {
        "kind": action.kind, "target_node_1": action.target_node_1,
        "target_node_2": action.target_node_2, "prompt_id": action.prompt_id,
    }


def seed_hash(seed: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(seed, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def run_p8(seed: dict[str, Any], mode: P8Mode, *, evaluation_cache: EvaluationCache | None = None,
           env_factory=LocalPublicEnvironment):
    started = time.perf_counter()
    env = env_factory(seed)
    count = len(seed["nodes"])
    board = Blackboard(node_count=count)
    actions = dict.fromkeys(("scan", "comm", "cut", "shield"), 0)
    first_responses: dict[int, float] = {}
    deviations: list[dict[str, Any]] = []
    audit_rejections: list[dict[str, Any]] = []
    failures = planning_calls = rollouts = steps = 0
    limit = 117 if count <= 50 else 247
    for node_id in range(1, count + 1):
        action = Action("scan", node_id)
        budget = env.get_remaining_budget()
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal P8 scan")
        if not apply_action_outcome(env, board, action, budget).succeeded:
            raise RuntimeError("P8 scan failed")
        actions["scan"] += 1
        steps += 1
    salt = public_board_salt(board)
    while steps < limit:
        budget = env.get_remaining_budget()
        decision = choose_p8_action(
            board, budget, first_responses, remaining_steps=limit - steps,
            salt=salt, mode=mode, evaluation_cache=evaluation_cache,
        )
        planning_calls += 1
        rollouts += decision.rollouts
        action = decision.action
        if action is None:
            break
        diagnostic = {
            "step": steps + 1,
            "action": _action_payload(action),
            "baseline_action": _action_payload(decision.baseline_action),
            "proposed_action": _action_payload(decision.proposed_action or action),
            "source": decision.source, "mean_delta": decision.mean_delta,
            "minimum_delta": decision.minimum_delta,
            "paired_deltas": list(decision.paired_deltas),
            "audit_mean_delta": decision.audit_mean_delta,
            "audit_minimum_delta": decision.audit_minimum_delta,
            "audit_paired_deltas": list(decision.audit_paired_deltas),
            "compared_actions": [_action_payload(item) for item in decision.compared_actions],
        }
        if decision.deviated:
            deviations.append(diagnostic)
        elif (mode == "audited" and decision.proposed_action is not None
              and decision.proposed_action != decision.baseline_action):
            audit_rejections.append(diagnostic)
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal P8 planned action")
        old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        actions[action.kind] += 1
        steps += 1
        if not outcome.succeeded:
            failures += 1
            break
        if action.kind == "comm" and turn == 1:
            first_responses[action.target_node_1] = board.nodes[action.target_node_1].w - old_w
    return {
        "score": env.evaluate(), "actions": actions, "failures": failures,
        "remaining_budget": env.get_remaining_budget(), "steps": steps,
        "planning_calls": planning_calls, "rollouts": rollouts,
        "deviation_count": len(deviations), "deviations": deviations,
        "audit_rejection_count": len(audit_rejections),
        "audit_rejections": audit_rejections,
        "public_board_salt": salt, "seconds": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", nargs="+", choices=FAMILIES, default=list(OLD_FAMILIES))
    parser.add_argument("--repetitions", nargs="+", type=int, default=[501])
    parser.add_argument("--strata", nargs="+", choices=R_STRATA, default=["standard"])
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    cohort = parser.add_mutually_exclusive_group()
    cohort.add_argument("--confirm", action="store_true", help="Explicitly select the reserved confirmation cohort after freezing a variant")
    cohort.add_argument("--objective-confirm", action="store_true", help="Select the separately preregistered mean-objective cohort 701-705")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    families = tuple(dict.fromkeys(args.families))
    repetitions = tuple(dict.fromkeys(args.repetitions))
    strata = tuple(dict.fromkeys(args.strata))
    variants = tuple(dict.fromkeys(args.variants))
    allowed = tuple(range(701, 706)) if args.objective_confirm else (CONFIRMATION_REPETITIONS if args.confirm else DEVELOPMENT_REPETITIONS)
    if not repetitions or not set(repetitions).issubset(allowed):
        parser.error("Use 501-503, --confirm with 601-605, or --objective-confirm with 701-705")
    policy_path = ROOT / "src/starnet/policy/p8_experiment.py"
    policy_sha256 = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    config = {"block": "p8", "nodes": 50, "families": list(families),
              "repetitions": list(repetitions), "variants": list(variants),
              "strata": list(strata), "prior": "Uniform(0.2,1.5)",
              "sequential_screen": "five-scenario selection; audited adds eight independent paired scenarios without reselection",
              "policy_sha256": policy_sha256}
    progress_path = args.output.with_suffix(".progress.json")
    rows: list[dict[str, Any]] = []
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("config") != config:
            parser.error("progress config does not match requested P8 cohort")
        rows = list(progress.get("rows", []))
    completed = {(row["family"], row["repetition"], row["r_stratum"], row["variant"])
                 for row in rows}
    for family in families:
        for repetition in repetitions:
            for r_stratum in strata:
                seed = seed_payload(family, repetition, r_stratum)
                existing = next((row for row in rows if row["family"] == family
                                 and row["repetition"] == repetition
                                 and row["r_stratum"] == r_stratum), None)
                baseline = existing["baseline"] if existing else run_variant(seed, "public_greedy")
                cache: EvaluationCache = {}
                for variant in variants:
                    key = (family, repetition, r_stratum, variant)
                    if key in completed:
                        continue
                    candidate = run_p8(seed, variant, evaluation_cache=cache)
                    row = {
                        "family": family, "repetition": repetition,
                        "r_stratum": r_stratum, "seed_sha256": seed_hash(seed),
                        "variant": variant, "baseline": baseline, "candidate": candidate,
                        "delta": candidate["score"] - baseline["score"],
                    }
                    rows.append(row)
                    completed.add(key)
                    progress_path.parent.mkdir(parents=True, exist_ok=True)
                    progress_path.write_text(json.dumps({"config": config, "rows": rows},
                                             ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    print(json.dumps({
                        "family": family, "repetition": repetition, "r_stratum": r_stratum,
                        "variant": variant, "delta": row["delta"],
                        "score": candidate["score"], "failures": candidate["failures"],
                        "rollouts": candidate["rollouts"],
                        "deviation_count": candidate["deviation_count"],
                        "audit_rejection_count": candidate["audit_rejection_count"],
                        "seconds": candidate["seconds"],
                    }, ensure_ascii=False), flush=True)

    def summarize(selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary = {}
        for variant in variants:
            selected = [row for row in selected_rows if row["variant"] == variant]
            values = [row["delta"] for row in selected]
            family_means = {family: statistics.fmean(row["delta"] for row in selected
                                                      if row["family"] == family)
                            for family in families}
            summary[variant] = {
                "cases": len(selected), "mean_delta": statistics.fmean(values),
                "minimum_delta": min(values), "family_mean_delta": family_means,
                "all_family_means_nonnegative": min(family_means.values()) >= -1e-8,
                "failures": sum(row["candidate"]["failures"] for row in selected),
            }
        return summary

    stratum_summary = {stratum: summarize([row for row in rows if row["r_stratum"] == stratum])
                       for stratum in strata}
    report = {
        "config": config, "rows": rows,
        "summary": stratum_summary[strata[0]] if len(strata) == 1 else {},
        "stratum_summary": stratum_summary, "platform_score": None,
        "production_promotion_allowed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stratum_summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

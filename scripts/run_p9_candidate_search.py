#!/usr/bin/env python3
"""Run the preregistered P9 candidate-generation development comparison."""

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
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import LocalPublicEnvironment, run_variant
from scripts.run_p8_search import run_p8, seed_hash
from starnet.experiments.p8_seeds import FAMILIES, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.p8_experiment import EvaluationCache, public_board_salt
from starnet.policy.p9_experiment import P9Variant, choose_p9_action
from starnet.runtime.env_adapter import apply_action_outcome


VARIANTS: tuple[P9Variant, ...] = ("depth2", "portfolio")


def _payload(action: Action | None) -> dict[str, Any] | None:
    if action is None:
        return None
    return {
        "kind": action.kind,
        "target_node_1": action.target_node_1,
        "target_node_2": action.target_node_2,
        "prompt_id": action.prompt_id,
    }


def run_p9(seed: dict[str, Any], variant: P9Variant, *, cache: EvaluationCache | None = None):
    started = time.perf_counter()
    env = LocalPublicEnvironment(seed)
    count = len(seed["nodes"])
    board = Blackboard(node_count=count)
    actions = dict.fromkeys(("scan", "comm", "cut", "shield"), 0)
    observed: dict[int, float] = {}
    deviations: list[dict[str, Any]] = []
    steps = failures = planning_calls = rollouts = 0
    limit = 117
    for node_id in range(1, count + 1):
        action = Action("scan", node_id)
        budget = env.get_remaining_budget()
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal P9 scan")
        if not apply_action_outcome(env, board, action, budget).succeeded:
            raise RuntimeError("P9 scan failed")
        actions["scan"] += 1
        steps += 1
    salt = public_board_salt(board)
    while steps < limit:
        budget = env.get_remaining_budget()
        decision = choose_p9_action(
            board, budget, observed, remaining_steps=limit - steps, salt=salt,
            variant=variant, evaluation_cache=cache,
        )
        planning_calls += 1
        rollouts += decision.rollouts
        action = decision.action
        if action is None:
            break
        if decision.deviated:
            deviations.append({
                "step": steps + 1,
                "action": _payload(action),
                "baseline_action": _payload(decision.baseline_action),
                "source": decision.source,
                "mean_delta": decision.mean_delta,
                "minimum_delta": decision.minimum_delta,
                "domain_size": len(decision.compared_actions),
            })
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal P9 planned action")
        old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        actions[action.kind] += 1
        steps += 1
        if not outcome.succeeded:
            failures += 1
            break
        if action.kind == "comm" and turn == 1:
            assert old_w is not None
            observed[action.target_node_1] = board.nodes[action.target_node_1].w - old_w
    return {
        "score": env.evaluate(),
        "actions": actions,
        "failures": failures,
        "remaining_budget": env.get_remaining_budget(),
        "steps": steps,
        "planning_calls": planning_calls,
        "rollouts": rollouts,
        "deviation_count": len(deviations),
        "deviations": deviations,
        "seconds": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", nargs="+", choices=FAMILIES, default=list(FAMILIES))
    parser.add_argument("--repetitions", nargs="+", type=int, required=True)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repetitions = tuple(dict.fromkeys(args.repetitions))
    if not repetitions or not set(repetitions).issubset({501, 502, 503}):
        parser.error("P9 development permits only repetitions 501-503")
    families = tuple(dict.fromkeys(args.families))
    variants = tuple(dict.fromkeys(args.variants))
    policy_path = ROOT / "src/starnet/policy/p9_experiment.py"
    config = {
        "families": list(families),
        "repetitions": list(repetitions),
        "variants": list(variants),
        "stratum": "standard",
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
    }
    progress_path = args.output.with_suffix(".progress.json")
    rows: list[dict[str, Any]] = []
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("config") != config:
            parser.error("progress config does not match requested P9 cohort")
        rows = list(progress.get("rows", []))
    completed = {
        (row["family"], row["repetition"], row["variant"])
        for row in rows
    }
    for family in families:
        for repetition in repetitions:
            seed = seed_payload(family, repetition, "standard")
            existing = next(
                (row for row in rows if row["family"] == family and row["repetition"] == repetition),
                None,
            )
            public_greedy = existing["public_greedy"] if existing else run_variant(seed, "public_greedy")
            p8 = existing["p8"] if existing else run_p8(seed, "conservative")
            shared_cache: EvaluationCache = {}
            for variant in variants:
                key = (family, repetition, variant)
                if key in completed:
                    continue
                candidate = run_p9(seed, variant, cache=shared_cache)
                row = {
                    "family": family,
                    "repetition": repetition,
                    "seed_sha256": seed_hash(seed),
                    "variant": variant,
                    "public_greedy": public_greedy,
                    "p8": p8,
                    "candidate": candidate,
                    "delta_vs_public_greedy": candidate["score"] - public_greedy["score"],
                    "delta_vs_p8": candidate["score"] - p8["score"],
                }
                rows.append(row)
                completed.add(key)
                progress_path.parent.mkdir(parents=True, exist_ok=True)
                progress_path.write_text(
                    json.dumps({"config": config, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(json.dumps({
                    "family": family,
                    "repetition": repetition,
                    "variant": variant,
                    "delta_vs_p8": row["delta_vs_p8"],
                    "delta_vs_public_greedy": row["delta_vs_public_greedy"],
                    "seconds": candidate["seconds"],
                }), flush=True)
    summary = {}
    for variant in variants:
        selected = [row for row in rows if row["variant"] == variant]
        versus_p8 = [row["delta_vs_p8"] for row in selected]
        versus_greedy = [row["delta_vs_public_greedy"] for row in selected]
        summary[variant] = {
            "cases": len(selected),
            "mean_delta_vs_p8": statistics.fmean(versus_p8),
            "mean_delta_vs_public_greedy": statistics.fmean(versus_greedy),
            "minimum_delta_vs_p8": min(versus_p8),
            "win_tie_loss_vs_p8": [
                sum(value > 1e-8 for value in versus_p8),
                sum(abs(value) <= 1e-8 for value in versus_p8),
                sum(value < -1e-8 for value in versus_p8),
            ],
            "family_mean_delta_vs_p8": {
                family: statistics.fmean(row["delta_vs_p8"] for row in selected if row["family"] == family)
                for family in families
            },
            "failures": sum(row["candidate"]["failures"] for row in selected),
            "mean_seconds": statistics.fmean(row["candidate"]["seconds"] for row in selected),
        }
    report = {"config": config, "summary": summary, "rows": rows, "production_enabled": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

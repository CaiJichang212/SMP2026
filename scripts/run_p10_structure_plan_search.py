#!/usr/bin/env python3
"""Run the preregistered P10 full structural-plan development screen."""

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

from scripts.run_local_policy_matrix import LocalPublicEnvironment
from starnet.experiments.p8_seeds import FAMILIES, seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.p8_experiment import EvaluationCache, choose_p8_action, public_board_salt
from starnet.policy.p10_structure_plan_experiment import choose_full_plan
from starnet.runtime.env_adapter import apply_action_outcome


DEVELOPMENT_FAMILIES = tuple(FAMILIES[:6])
VARIANTS = {"beam4": (4, 8), "beam6": (6, 8)}


def _payload(action: Action) -> dict[str, Any]:
    return {
        "kind": action.kind,
        "target_node_1": action.target_node_1,
        "target_node_2": action.target_node_2,
        "prompt_id": action.prompt_id,
    }


def _seed_hash(seed: dict[str, Any]) -> str:
    encoded = json.dumps(seed, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _execute(env, board, action, observed, actions, interventions):
    budget = env.get_remaining_budget()
    if not is_legal_action(action, board, budget):
        raise RuntimeError("illegal real P10 action")
    old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
    turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
    outcome = apply_action_outcome(env, board, action, budget)
    actions[action.kind] += 1
    interventions.append(_payload(action))
    if not outcome.succeeded:
        raise RuntimeError("failed real P10 action")
    if action.kind == "comm" and turn == 1:
        observed[action.target_node_1] = board.nodes[action.target_node_1].w - old_w


def run_policy(seed: dict[str, Any], variant: str | None):
    started = time.perf_counter()
    env = LocalPublicEnvironment(seed)
    board = Blackboard(node_count=50)
    observed: dict[int, float] = {}
    actions = dict.fromkeys(("scan", "comm", "cut", "shield"), 0)
    interventions: list[dict[str, Any]] = []
    steps = 0
    for node_id in range(1, 51):
        action = Action("scan", node_id)
        budget = env.get_remaining_budget()
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal P10 scan")
        if not apply_action_outcome(env, board, action, budget).succeeded:
            raise RuntimeError("failed P10 scan")
        actions["scan"] += 1
        steps += 1
    salt = public_board_salt(board)
    plan_diagnostic = None
    p8_cache: EvaluationCache = {}
    if variant is not None:
        max_structures, beam_width = VARIANTS[variant]
        decision = choose_full_plan(
            board, env.get_remaining_budget(), observed,
            remaining_steps=117 - steps, salt=salt,
            max_structures=max_structures, beam_width=beam_width,
        )
        plan = decision.plan
        plan_diagnostic = {
            "accepted": decision.accepted,
            "rollouts": decision.rollouts,
            "baseline_action": _payload(decision.baseline_action) if decision.baseline_action else None,
            "selection_deltas": list(decision.selection_deltas),
            "audit_deltas": list(decision.audit_deltas),
            "structure_actions": [_payload(action) for action in plan.structure_actions] if plan else [],
            "persuasion_actions": [_payload(action) for action in plan.persuasion_actions] if plan else [],
            "predicted_score": plan.predicted_score if plan else None,
            "predicted_gain": plan.predicted_gain if plan else None,
            "root_actions": plan.root_actions if plan else 0,
            "expanded_states": plan.expanded_states if plan else 0,
            "planning_seconds": plan.planning_seconds if plan else 0.0,
        }
        if decision.accepted:
            for action in decision.actions:
                if steps >= 117:
                    raise RuntimeError("accepted P10 plan exceeds step limit")
                _execute(env, board, action, observed, actions, interventions)
                steps += 1

    # A rejected plan is exactly the bounded P9 fallback. An accepted complete
    # structural prefix returns all persuasion resources to the adaptive P9
    # continuation; the fixed mean tail remains search diagnostics only.
    while steps < 117:
        budget = env.get_remaining_budget()
        decision = choose_p8_action(
            board, budget, observed, remaining_steps=117 - steps,
            salt=salt, mode="conservative", evaluation_cache=p8_cache,
        )
        if decision.action is None:
            break
        _execute(env, board, decision.action, observed, actions, interventions)
        steps += 1
    return {
        "score": env.evaluate(),
        "remaining_budget": env.get_remaining_budget(),
        "steps": steps,
        "actions": actions,
        "interventions": interventions,
        "failures": 0,
        "plan": plan_diagnostic,
        "seconds": time.perf_counter() - started,
    }


def _first_divergence(left, right):
    width = max(len(left), len(right))
    for index in range(width):
        first = left[index] if index < len(left) else None
        second = right[index] if index < len(right) else None
        if first != second:
            return {"intervention_index": index + 1, "candidate": first, "baseline": second}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", nargs="+", choices=DEVELOPMENT_FAMILIES,
                        default=list(DEVELOPMENT_FAMILIES))
    parser.add_argument("--variants", nargs="+", choices=tuple(VARIANTS),
                        default=list(VARIANTS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    families = tuple(dict.fromkeys(args.families))
    variants = tuple(dict.fromkeys(args.variants))
    config = {
        "protocol": "p10-full-structure-plan-development-20260914",
        "families": list(families), "repetitions": [501],
        "variants": list(variants), "workers": 1,
        "policy_sha256": hashlib.sha256(
            (ROOT / "src/starnet/policy/p10_structure_plan_experiment.py").read_bytes()
        ).hexdigest(),
    }
    progress = args.output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("progress config differs from P10 request")
        rows = list(saved.get("rows", []))
    completed = {(row["family"], row["variant"]) for row in rows}
    for family in families:
        seed = seed_payload(family, 501, "standard")
        existing = next((row for row in rows if row["family"] == family), None)
        baseline = existing["baseline"] if existing else run_policy(seed, None)
        for variant in variants:
            if (family, variant) in completed:
                continue
            candidate = run_policy(seed, variant)
            row = {
                "family": family, "repetition": 501, "shift_stratum": "standard",
                "seed_sha256": _seed_hash(seed), "variant": variant,
                "baseline": baseline, "candidate": candidate,
                "delta": candidate["score"] - baseline["score"],
                "first_divergence": _first_divergence(
                    candidate["interventions"], baseline["interventions"],
                ),
            }
            rows.append(row)
            completed.add((family, variant))
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps({"config": config, "rows": rows},
                                           ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({
                "family": family, "variant": variant, "delta": row["delta"],
                "accepted": bool(candidate["plan"] and candidate["plan"]["accepted"]),
                "structure_actions": len(candidate["plan"]["structure_actions"]) if candidate["plan"] else 0,
                "seconds": candidate["seconds"],
            }), flush=True)
    summary = {}
    for variant in variants:
        selected = [row for row in rows if row["variant"] == variant]
        deltas = [row["delta"] for row in selected]
        summary[variant] = {
            "cases": len(selected), "mean_delta": statistics.fmean(deltas),
            "minimum_delta": min(deltas), "maximum_delta": max(deltas),
            "win_tie_loss": [sum(x > 1e-8 for x in deltas),
                             sum(abs(x) <= 1e-8 for x in deltas),
                             sum(x < -1e-8 for x in deltas)],
            "accepted_plans": sum(bool(row["candidate"]["plan"] and
                                       row["candidate"]["plan"]["accepted"])
                                  for row in selected),
            "mean_seconds": statistics.fmean(row["candidate"]["seconds"] for row in selected),
            "failures": sum(row["candidate"]["failures"] for row in selected),
        }
    report = {"config": config, "summary": summary, "rows": rows,
              "confirmation_opened": False, "production_enabled": False}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

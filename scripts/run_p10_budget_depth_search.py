#!/usr/bin/env python3
"""Run the preregistered depth-12 strict versus mean-audited P10 screen."""

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

from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p10_structure_plan_search import (
    DEVELOPMENT_FAMILIES, _execute, _first_divergence, _seed_hash, run_policy,
)
from starnet.experiments.p8_seeds import seed_payload as p8_seed_payload
from starnet.experiments.seeds import seed_payload as legacy_seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.p8_experiment import choose_p8_action, public_board_salt
from starnet.policy.p10_structure_plan_experiment import (
    FullStructurePlan, RiskMode, choose_full_plan, search_full_structure_plan,
)
from starnet.runtime.env_adapter import apply_action_outcome


RISK_MODES: tuple[RiskMode, ...] = ("strict", "mean_audited")
COHORTS = ("p8_501", "legacy_rep1")


def _seed(cohort: str, family: str):
    if cohort == "p8_501":
        return p8_seed_payload(family, 501, "standard")
    if cohort == "legacy_rep1":
        return legacy_seed_payload(family, 50, 1)
    raise ValueError("unknown P10 cohort")


def _scanned_board(seed):
    board = Blackboard(node_count=50)
    neighbors = {node_id: [] for node_id in range(1, 51)}
    for left, right in seed["edges"]:
        neighbors[int(left)].append(int(right))
        neighbors[int(right)].append(int(left))
    for item in seed["nodes"]:
        node_id = int(item["id"])
        board.record_scan(node_id, {
            "w": float(item["w"]), "persona": str(item["persona"]),
            "comm_left": int(item["comm_left"]), "neighbors": neighbors[node_id],
        })
    return board


def run_candidate(seed, plan: FullStructurePlan | None, risk_mode: RiskMode):
    started = time.perf_counter()
    env = LocalPublicEnvironment(seed)
    board = Blackboard(node_count=50)
    observed = {}
    actions = dict.fromkeys(("scan", "comm", "cut", "shield"), 0)
    interventions = []
    steps = 0
    for node_id in range(1, 51):
        action = Action("scan", node_id)
        budget = env.get_remaining_budget()
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal P10 depth scan")
        if not apply_action_outcome(env, board, action, budget).succeeded:
            raise RuntimeError("failed P10 depth scan")
        actions["scan"] += 1
        steps += 1
    salt = public_board_salt(board)
    decision = choose_full_plan(
        board, env.get_remaining_budget(), observed,
        remaining_steps=117 - steps, salt=salt,
        max_structures=12, beam_width=4, risk_mode=risk_mode,
        proposed_plan=plan,
    )
    if decision.accepted:
        for action in decision.actions:
            _execute(env, board, action, observed, actions, interventions)
            steps += 1
    while steps < 117:
        p8 = choose_p8_action(
            board, env.get_remaining_budget(), observed,
            remaining_steps=117 - steps, salt=salt, mode="conservative",
        )
        if p8.action is None:
            break
        _execute(env, board, p8.action, observed, actions, interventions)
        steps += 1
    plan_data = None if plan is None else {
        "structure_actions": [action.__dict__ for action in plan.structure_actions],
        "persuasion_actions": [action.__dict__ for action in plan.persuasion_actions],
        "predicted_gain": plan.predicted_gain,
        "root_actions": plan.root_actions,
        "expanded_states": plan.expanded_states,
        "planning_seconds": plan.planning_seconds,
    }
    return {
        "score": env.evaluate(), "remaining_budget": env.get_remaining_budget(),
        "steps": steps, "actions": actions, "interventions": interventions,
        "failures": 0, "accepted": decision.accepted,
        "selection_deltas": list(decision.selection_deltas),
        "audit_deltas": list(decision.audit_deltas),
        "plan": plan_data, "execution_seconds": time.perf_counter() - started,
        "seconds_including_search": time.perf_counter() - started + (plan.planning_seconds if plan else 0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohorts", nargs="+", choices=COHORTS, default=list(COHORTS))
    parser.add_argument("--families", nargs="+", choices=DEVELOPMENT_FAMILIES,
                        default=list(DEVELOPMENT_FAMILIES))
    parser.add_argument("--risk-modes", nargs="+", choices=RISK_MODES,
                        default=list(RISK_MODES))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cohorts = tuple(dict.fromkeys(args.cohorts))
    families = tuple(dict.fromkeys(args.families))
    risk_modes = tuple(dict.fromkeys(args.risk_modes))
    config = {
        "protocol": "p10-budget-depth-mean-development-20260914",
        "cohorts": list(cohorts), "families": list(families),
        "risk_modes": list(risk_modes), "max_structures": 12,
        "beam_width": 4, "workers": 1,
        "policy_sha256": hashlib.sha256(
            (ROOT / "src/starnet/policy/p10_structure_plan_experiment.py").read_bytes()
        ).hexdigest(),
    }
    progress = args.output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("progress config differs from P10 depth request")
        rows = list(saved.get("rows", []))
    completed = {(row["cohort"], row["family"], row["risk_mode"]) for row in rows}
    for cohort in cohorts:
        for family in families:
            seed = _seed(cohort, family)
            existing = next((row for row in rows if row["cohort"] == cohort
                             and row["family"] == family), None)
            baseline = existing["baseline"] if existing else run_policy(seed, None)
            board = _scanned_board(seed)
            plan = search_full_structure_plan(
                board, 75.0, {}, remaining_steps=67,
                max_structures=12, beam_width=4,
            )
            for risk_mode in risk_modes:
                key = cohort, family, risk_mode
                if key in completed:
                    continue
                candidate = run_candidate(seed, plan, risk_mode)
                row = {
                    "cohort": cohort, "family": family,
                    "repetition": 501 if cohort == "p8_501" else 1,
                    "seed_sha256": _seed_hash(seed), "risk_mode": risk_mode,
                    "baseline": baseline, "candidate": candidate,
                    "delta": candidate["score"] - baseline["score"],
                    "first_divergence": _first_divergence(
                        candidate["interventions"], baseline["interventions"],
                    ),
                }
                rows.append(row)
                completed.add(key)
                progress.parent.mkdir(parents=True, exist_ok=True)
                progress.write_text(json.dumps({"config": config, "rows": rows},
                                               ensure_ascii=False, indent=2) + "\n")
                print(json.dumps({
                    "cohort": cohort, "family": family, "risk_mode": risk_mode,
                    "delta": row["delta"], "accepted": candidate["accepted"],
                    "structure_actions": len(plan.structure_actions) if plan else 0,
                    "seconds": candidate["seconds_including_search"],
                }), flush=True)

    def summarize(selected):
        deltas = [row["delta"] for row in selected]
        return {
            "cases": len(selected), "mean_delta": statistics.fmean(deltas),
            "minimum_delta": min(deltas), "maximum_delta": max(deltas),
            "win_tie_loss": [sum(x > 1e-8 for x in deltas),
                             sum(abs(x) <= 1e-8 for x in deltas),
                             sum(x < -1e-8 for x in deltas)],
            "accepted": sum(row["candidate"]["accepted"] for row in selected),
            "failures": sum(row["candidate"]["failures"] for row in selected),
            "mean_seconds": statistics.fmean(
                row["candidate"]["seconds_including_search"] for row in selected
            ),
        }

    summary = {
        mode: {
            "overall": summarize([row for row in rows if row["risk_mode"] == mode]),
            "by_cohort": {cohort: summarize([row for row in rows
                                              if row["risk_mode"] == mode and row["cohort"] == cohort])
                          for cohort in cohorts},
        }
        for mode in risk_modes
    }
    report = {"config": config, "summary": summary, "rows": rows,
              "confirmation_opened": False, "production_enabled": False}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

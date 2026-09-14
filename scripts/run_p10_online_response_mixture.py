#!/usr/bin/env python3
"""Evaluate an online public-response mixture on consumed development cases."""

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

from scripts.run_p10_greedy_factor_attribution import first_divergence
from scripts.run_p9_distribution_validation import LoggedEnvironment
from starnet.experiments.p9_distribution_seeds import seed_payload as p9_seed_payload
from starnet.experiments.seeds import SEED_SPECS, seed_payload as legacy_seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.baseline import public_response
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.structural import ExperimentalPublicGreedyPlanner
from starnet.runtime.env_adapter import apply_action_outcome


from starnet.policy.public_response_mixture import PublicResponseMixtureLedger


PROTOCOL = ROOT / "experiments/manifests/p10-gated-online-mixture-development-20260914.json"
ARMS = (
    "mixture__unrestricted", "gated__unrestricted", "fixed__unrestricted",
    "mixture__full_gate", "gated__full_gate", "fixed__full_gate",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


OnlineResponseMixture = PublicResponseMixtureLedger


def action_payload(action: Action | None):
    if action is None:
        return None
    return {"kind": action.kind, "target_node_1": action.target_node_1,
            "target_node_2": action.target_node_2, "prompt_id": action.prompt_id}


def response_fn(estimator: str, board: Blackboard, observed: dict[int, float],
                mixture: OnlineResponseMixture):
    if estimator in {"mixture", "gated"}:
        def estimate(node_id, node, turn):
            return mixture.predict(
                node_id, node.persona, turn, observed, gated=estimator == "gated",
            )
        return estimate
    return lambda node_id, node, turn: public_response(
        node_id, node.persona, turn, observed, DEFAULT_CALIBRATION_PROFILE, None,
    )


def candidates(board: Blackboard, budget: float, observed: dict[int, float],
               mixture: OnlineResponseMixture, arm: str):
    estimator, structure = arm.split("__", 1)
    planner = ExperimentalPublicGreedyPlanner(
        response_fn(estimator, board, observed, mixture),
        candidate_limit=len(board.edges) + 2 * len(board.nodes) + 1,
        conservative_structure=structure == "full_gate",
        min_observed_responses=0,
        structure_roi_margin=1.0,
    )
    return planner.candidates(board, budget, observed_response_count=len(observed))


def run_arm(seed: dict, arm: str) -> dict:
    started = time.perf_counter()
    env = LoggedEnvironment(seed)
    board = Blackboard(node_count=len(seed["nodes"]))
    observed: dict[int, float] = {}
    mixture = OnlineResponseMixture()
    decisions = []
    for node_id in range(1, len(seed["nodes"]) + 1):
        if not apply_action_outcome(env, board, Action("scan", node_id),
                                    env.get_remaining_budget()).succeeded:
            raise RuntimeError("scan failed")
    while len(env.action_log) < 117:
        budget = env.get_remaining_budget()
        ranked = candidates(board, budget, observed, mixture, arm)
        selected = ranked[0] if ranked else None
        decisions.append({
            "action_index": len(env.action_log) + 1,
            "budget": budget,
            "posterior_weights": mixture.weights(),
            "mixture_gate_open": mixture.gate_open(),
            "selected_action": action_payload(selected.action if selected else None),
            "selected_candidate_id": selected.candidate_id if selected else None,
            "candidate_ids_by_kind": {
                kind: [item.candidate_id for item in ranked if item.action.kind == kind]
                for kind in ("comm", "cut", "shield")
            },
            "candidate_actions": [action_payload(item.action) for item in ranked],
        })
        if selected is None:
            break
        action = selected.action
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal selected action")
        old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
        persona = board.nodes[action.target_node_1].persona if action.kind == "comm" else None
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        if not outcome.succeeded:
            raise RuntimeError("action failed")
        if action.kind == "comm" and turn == 1:
            new_w = board.nodes[action.target_node_1].w
            observed[action.target_node_1] = new_w - old_w
            if arm.startswith(("mixture__", "gated__")):
                mixture.observe_first(persona, old_w, new_w)
    return {
        "score": env.evaluate(), "remaining_budget": env.get_remaining_budget(),
        "action_attempts": len(env.action_log), "action_failures": 0,
        "action_log_sha256": json_digest(env.action_log), "action_log": env.action_log,
        "decisions": decisions, "final_weights": mixture.weights(),
        "gate_activation": mixture.activation,
        "pre_gate_decisions": sum(not item["mixture_gate_open"] for item in decisions),
        "accepted_observations": mixture.accepted, "censored_observations": mixture.censored,
        "elapsed_seconds": time.perf_counter() - started,
    }


def registry():
    result = []
    for family in SEED_SPECS:
        result.append((f"legacy:{family}:1", "legacy_independent",
                       legacy_seed_payload(family, 50, 1)))
    for family in ("er_resampled", "ba_resampled", "ws_resampled", "sbm_resampled"):
        for shift in ("centered_independent", "negative_persona_aligned",
                      "positive_persona_inverse"):
            result.append((f"p9:{family}:901:{shift}", shift,
                           p9_seed_payload(family, 901, shift)))
    return result


def comparisons():
    result = []
    for structure in ("unrestricted", "full_gate"):
        result.extend((
            (f"gated__{structure}", f"fixed__{structure}", "gated_vs_fixed"),
            (f"gated__{structure}", f"mixture__{structure}", "gated_vs_soft"),
            (f"mixture__{structure}", f"fixed__{structure}", "mixture_vs_fixed"),
        ))
    for estimator in ("mixture", "gated", "fixed"):
        result.append((f"{estimator}__unrestricted", f"{estimator}__full_gate",
                       "unrestricted_vs_full_gate"))
    return result


def metric(rows, left, right):
    values = [row["arms"][left]["score"] - row["arms"][right]["score"] for row in rows]
    return {"cases": len(values), "mean": statistics.fmean(values),
            "minimum": min(values), "maximum": max(values),
            "win_tie_loss": [sum(x > 1e-8 for x in values),
                             sum(abs(x) <= 1e-8 for x in values),
                             sum(x < -1e-8 for x in values)]}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-output", type=Path,
                        default=ROOT / "experiments/raw/p10-gated-online-mixture-20260914/full.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "experiments/reports/p10-gated-online-mixture-20260914.json")
    args = parser.parse_args()
    config = {"protocol_sha256": digest(PROTOCOL), "runner_sha256": digest(Path(__file__)),
              "arms": list(ARMS), "cases": 18, "worker_limit": 1,
              "case_status": "previously_consumed"}
    progress_path = args.raw_output.with_suffix(".progress.json")
    rows = []
    if progress_path.exists():
        previous = json.loads(progress_path.read_text(encoding="utf-8"))
        if previous.get("config") != config:
            parser.error("progress identity mismatch")
        rows = list(previous["rows"])
    completed = {row["case_id"] for row in rows}
    for case_id, stratum, seed in registry():
        if case_id in completed:
            continue
        arms = {arm: run_arm(seed, arm) for arm in ARMS}
        contrasts = {
            f"{factor}:{left}:{right}": first_divergence(arms[left], arms[right])
            for left, right, factor in comparisons()
        }
        rows.append({"case_id": case_id, "stratum": stratum,
                     "seed_sha256": json_digest(seed), "arms": arms,
                     "contrasts": contrasts})
        write_json(progress_path, {"config": config, "rows": rows})
        print(json.dumps({"case_id": case_id, "completed": len(rows),
                          "scores": {arm: value["score"] for arm, value in arms.items()}},
                         ensure_ascii=False), flush=True)
    raw = {"config": config, "complete": len(rows) == 18, "rows": rows}
    write_json(args.raw_output, raw)
    groups = {stratum: [row for row in rows if row["stratum"] == stratum]
              for stratum in ("legacy_independent", "centered_independent",
                              "negative_persona_aligned", "positive_persona_inverse")}
    compact = {
        "config": config, "complete": raw["complete"],
        "raw_log": {"path": str(args.raw_output.relative_to(ROOT)),
                    "sha256": digest(args.raw_output), "committed": False},
        "overall": {f"{factor}:{left}:{right}": metric(rows, left, right)
                    for left, right, factor in comparisons()},
        "by_stratum": {
            stratum: {
                f"{factor}:{left}:{right}": metric(selected, left, right)
                for left, right, factor in comparisons()
            } for stratum, selected in groups.items()
        },
        "rows": [{
            "case_id": row["case_id"], "stratum": row["stratum"],
            "seed_sha256": row["seed_sha256"], "contrasts": row["contrasts"],
            "arms": {arm: {"score": value["score"],
                            "remaining_budget": value["remaining_budget"],
                            "action_attempts": value["action_attempts"],
                            "action_failures": value["action_failures"],
                            "action_log_sha256": value["action_log_sha256"],
                            "final_weights": value["final_weights"],
                            "gate_activation": value["gate_activation"],
                            "pre_gate_decisions": value["pre_gate_decisions"],
                            "accepted_observation_count": len(value["accepted_observations"]),
                            "censored_observation_count": len(value["censored_observations"])}
                     for arm, value in row["arms"].items()}
        } for row in rows],
        "production_enabled": False, "platform_score": None,
    }
    write_json(args.output, compact)
    print(json.dumps({"complete": compact["complete"], "overall": compact["overall"]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

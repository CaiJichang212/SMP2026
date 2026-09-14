#!/usr/bin/env python3
"""Run the preregistered fast greedy factor attribution on consumed cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_p9_distribution_validation import LoggedEnvironment
from starnet.experiments.p9_distribution_seeds import seed_payload as p9_seed_payload
from starnet.experiments.seeds import SEED_SPECS, seed_payload as legacy_seed_payload
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.baseline import _response, public_response
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.policy.structural import (
    ExperimentalPublicGreedyPlanner,
    public_positive_graph_gate_closed,
)
from starnet.runtime.env_adapter import apply_action_outcome


PROTOCOL = ROOT / "experiments/manifests/p10-greedy-factor-attribution-20260914.json"
P9_FAILURE_CASES = (
    ("ba_resampled", 902, "saturated_hubs"),
    ("ba_resampled", 901, "saturated_hubs"),
    ("ba_resampled", 1003, "saturated_hubs"),
    ("ba_resampled", 1002, "saturated_hubs"),
    ("ba_resampled", 1001, "saturated_hubs"),
    ("ba_resampled", 902, "compressed_degree_negative"),
    ("ba_resampled", 1002, "wide_degree_positive"),
    ("ba_resampled", 1001, "compressed_degree_negative"),
    ("sbm_resampled", 1001, "saturated_hubs"),
    ("ba_resampled", 1003, "wide_degree_positive"),
    ("ba_resampled", 1001, "wide_degree_positive"),
    ("sbm_resampled", 901, "positive_persona_inverse"),
)
ARMS = (
    "pooled__unrestricted",
    "fixed__unrestricted",
    "persona__unrestricted",
    "pooled__direction_roi",
    "fixed__direction_roi",
    "persona__direction_roi",
    "pooled__full_gate",
    "fixed__full_gate",
    "persona__full_gate",
    "fixed__full_gate_plus_negative_negative_cut",
    "hybrid__full_gate",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def action_payload(action: Action | None):
    if action is None:
        return None
    return {
        "kind": action.kind,
        "target_node_1": action.target_node_1,
        "target_node_2": action.target_node_2,
        "prompt_id": action.prompt_id,
    }


def action_key(action: Action) -> tuple[object, ...]:
    return action.kind, action.target_node_1, action.target_node_2, action.prompt_id


def candidate_key(candidate) -> tuple[object, ...]:
    return action_key(candidate.action)


def _response_fn(estimator: str, board: Blackboard, observed: dict[int, float]):
    if estimator == "hybrid":
        selected = _response if public_positive_graph_gate_closed(board) else public_response
    elif estimator == "pooled":
        selected = _response
    elif estimator == "fixed":
        selected = public_response
    elif estimator == "persona":
        first_slot = {"和平": 20.25, "中立": 15.0, "暴力": 3.0}

        def persona_response(node_id, persona, turn, responses, _profile, _ledger):
            observed_value = responses.get(node_id)
            first = (
                float(observed_value)
                if observed_value is not None
                else first_slot.get(persona, 12.75)
            )
            return max(0.0, first) * (0.5 ** (turn - 1))

        selected = persona_response
    else:
        raise ValueError("unknown response estimator")
    return lambda node_id, node, turn: selected(
        node_id, node.persona, turn, observed, DEFAULT_CALIBRATION_PROFILE, None,
    )


def _negative_nonpeace(board: Blackboard, node_id: int) -> bool:
    node = board.nodes.get(node_id)
    return node is not None and node.w < 0.0 and node.persona != "和平"


def generate_candidates(
    board: Blackboard, budget: float, observed: dict[int, float], arm: str,
):
    if arm == "hybrid__full_gate":
        estimator, structure = "hybrid", "full_gate"
    elif arm == "fixed__full_gate_plus_negative_negative_cut":
        estimator, structure = "fixed", "narrow_negative_cut"
    else:
        estimator, structure = arm.split("__", 1)
    limit = len(board.edges) + 2 * len(board.nodes) + 1
    response_fn = _response_fn(estimator, board, observed)

    def planner(conservative: bool):
        return ExperimentalPublicGreedyPlanner(
            response_fn,
            candidate_limit=max(1, limit),
            conservative_structure=conservative,
            min_observed_responses=0,
            structure_roi_margin=1.0,
        )

    if structure == "unrestricted":
        return planner(False).candidates(board, budget, observed_response_count=len(observed))
    if structure == "direction_roi":
        with patch("starnet.policy.structural.public_positive_graph_gate_closed", return_value=False):
            return planner(True).candidates(board, budget, observed_response_count=len(observed))
    full = planner(True).candidates(board, budget, observed_response_count=len(observed))
    if structure == "full_gate":
        return full
    if structure != "narrow_negative_cut":
        raise ValueError("unknown structure mode")
    unrestricted = planner(False).candidates(
        board, budget, observed_response_count=len(observed),
    )
    by_action = {candidate.action: candidate for candidate in full}
    for candidate in unrestricted:
        action = candidate.action
        if (
            action.kind == "cut"
            and action.target_node_2 is not None
            and _negative_nonpeace(board, action.target_node_1)
            and _negative_nonpeace(board, action.target_node_2)
        ):
            by_action.setdefault(action, candidate)
    return sorted(
        by_action.values(),
        key=lambda item: (-round(item.roi, 10), -round(item.score, 10), item.candidate_id),
    )


def run_arm(seed: dict, arm: str) -> dict:
    started = time.perf_counter()
    env = LoggedEnvironment(seed)
    board = Blackboard(node_count=len(seed["nodes"]))
    observed: dict[int, float] = {}
    decisions = []
    for node_id in range(1, len(seed["nodes"]) + 1):
        action = Action("scan", node_id)
        budget = env.get_remaining_budget()
        if not apply_action_outcome(env, board, action, budget).succeeded:
            raise RuntimeError("scan failed")
    while len(env.action_log) < 117:
        budget = env.get_remaining_budget()
        candidates = generate_candidates(board, budget, observed, arm)
        by_kind = {
            kind: [candidate.candidate_id for candidate in candidates if candidate.action.kind == kind]
            for kind in ("comm", "cut", "shield")
        }
        selected = candidates[0] if candidates else None
        decisions.append({
            "action_index": len(env.action_log) + 1,
            "budget": budget,
            "positive_graph_gate_closed": public_positive_graph_gate_closed(board),
            "selected_action": action_payload(selected.action if selected else None),
            "selected_candidate_id": selected.candidate_id if selected else None,
            "selected_score": selected.score if selected else None,
            "selected_roi": selected.roi if selected else None,
            "candidate_ids_by_kind": by_kind,
            "candidate_actions": [action_payload(candidate.action) for candidate in candidates],
        })
        if selected is None:
            break
        action = selected.action
        if not is_legal_action(action, board, budget):
            raise RuntimeError("planner returned an illegal action")
        old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        if not outcome.succeeded:
            raise RuntimeError("greedy action failed")
        if action.kind == "comm" and turn == 1:
            observed[action.target_node_1] = board.nodes[action.target_node_1].w - old_w
    return {
        "score": env.evaluate(),
        "remaining_budget": env.get_remaining_budget(),
        "action_attempts": len(env.action_log),
        "action_failures": sum(not item["success"] for item in env.action_log),
        "action_log_sha256": json_digest(env.action_log),
        "action_log": env.action_log,
        "decisions": decisions,
        "positive_gate_decisions": sum(item["positive_graph_gate_closed"] for item in decisions),
        "elapsed_seconds": time.perf_counter() - started,
    }


def first_divergence(left: dict, right: dict):
    left_steps, right_steps = left["decisions"], right["decisions"]
    for index in range(max(len(left_steps), len(right_steps))):
        first = left_steps[index] if index < len(left_steps) else None
        second = right_steps[index] if index < len(right_steps) else None
        first_action = first["selected_action"] if first else None
        second_action = second["selected_action"] if second else None
        if first_action == second_action:
            continue
        first_candidates = {
            tuple(action.get(key) for key in ("kind", "target_node_1", "target_node_2", "prompt_id"))
            for action in (first["candidate_actions"] if first else [])
        }
        second_candidates = {
            tuple(action.get(key) for key in ("kind", "target_node_1", "target_node_2", "prompt_id"))
            for action in (second["candidate_actions"] if second else [])
        }
        first_key = tuple(first_action.get(key) for key in ("kind", "target_node_1", "target_node_2", "prompt_id")) if first_action else None
        second_key = tuple(second_action.get(key) for key in ("kind", "target_node_1", "target_node_2", "prompt_id")) if second_action else None
        classification = (
            "ranking_only"
            if first_key in second_candidates and second_key in first_candidates
            else "candidate_set_changing"
        )
        return {
            "decision_index": index + 1,
            "classification": classification,
            "left_selected": first_action,
            "right_selected": second_action,
            "left_budget": first["budget"] if first else None,
            "right_budget": second["budget"] if second else None,
            "left_only_by_kind": {
                kind: len(set(first["candidate_ids_by_kind"][kind]) - set(second["candidate_ids_by_kind"][kind]))
                for kind in ("comm", "cut", "shield")
            } if first and second else None,
            "right_only_by_kind": {
                kind: len(set(second["candidate_ids_by_kind"][kind]) - set(first["candidate_ids_by_kind"][kind]))
                for kind in ("comm", "cut", "shield")
            } if first and second else None,
        }
    return None


def case_registry():
    cases = []
    for family in SEED_SPECS:
        seed = legacy_seed_payload(family, 50, 1)
        cases.append((f"legacy:{family}:1", seed, "consumed_legacy_six"))
    for family in ("er_resampled", "ba_resampled", "ws_resampled", "sbm_resampled"):
        for shift in ("centered_independent", "negative_persona_aligned"):
            seed = p9_seed_payload(family, 901, shift)
            cases.append((f"persona:{family}:901:{shift}", seed, "consumed_persona_axis"))
    for family, repetition, shift in P9_FAILURE_CASES:
        seed = p9_seed_payload(
            family, repetition, shift, allow_confirmation=repetition >= 1000,
        )
        cases.append((f"p9:{family}:{repetition}:{shift}", seed, "consumed_prior_loss"))
    return cases


def contrast_pairs():
    pairs = []
    for structure in ("unrestricted", "direction_roi", "full_gate"):
        pairs.append((f"pooled__{structure}", f"fixed__{structure}", "response_pooling"))
        pairs.append((f"persona__{structure}", f"fixed__{structure}", "persona_prior"))
    for response in ("pooled", "fixed", "persona"):
        pairs.append((f"{response}__unrestricted", f"{response}__direction_roi", "direction_roi_gate"))
        pairs.append((f"{response}__direction_roi", f"{response}__full_gate", "positive_graph_gate"))
    pairs.append(("fixed__full_gate_plus_negative_negative_cut", "fixed__full_gate", "negative_negative_cut"))
    pairs.append(("hybrid__full_gate", "fixed__full_gate", "hybrid_response_switch"))
    return pairs


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def summarize(rows: list[dict]):
    result = {}
    for left, right, factor in contrast_pairs():
        values = [row["arms"][left]["score"] - row["arms"][right]["score"] for row in rows]
        divergences = [row["contrasts"][factor + ":" + left + ":" + right] for row in rows]
        result[factor + ":" + left + ":" + right] = {
            "mean_delta": statistics.fmean(values),
            "minimum_delta": min(values),
            "win_tie_loss": [
                sum(value > 1e-8 for value in values),
                sum(abs(value) <= 1e-8 for value in values),
                sum(value < -1e-8 for value in values),
            ],
            "first_divergence_classification": {
                kind: sum(item is not None and item["classification"] == kind for item in divergences)
                for kind in ("ranking_only", "candidate_set_changing")
            },
            "no_divergence": sum(item is None for item in divergences),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "experiments/reports/p10-greedy-factor-attribution-20260914.json",
    )
    args = parser.parse_args()
    config = {
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "policy_sources": {
            path: digest(ROOT / path) for path in (
                "src/starnet/policy/baseline.py",
                "src/starnet/policy/cmg.py",
                "src/starnet/policy/structural.py",
            )
        },
        "arms": list(ARMS),
        "cases": 26,
        "worker_limit": 1,
        "case_status": "previously_consumed_mechanism_attribution",
    }
    progress_path = args.output.with_suffix(".progress.json")
    rows = []
    if progress_path.exists():
        previous = json.loads(progress_path.read_text(encoding="utf-8"))
        if previous.get("config") != config:
            parser.error("existing progress uses a different frozen configuration")
        rows = list(previous.get("rows", []))
    completed = {row["case_id"] for row in rows}
    for case_id, seed, status in case_registry():
        if case_id in completed:
            continue
        arms = {arm: run_arm(seed, arm) for arm in ARMS}
        contrasts = {}
        for left, right, factor in contrast_pairs():
            key = factor + ":" + left + ":" + right
            contrasts[key] = first_divergence(arms[left], arms[right])
        row = {
            "case_id": case_id,
            "case_status": status,
            "seed_sha256": json_digest(seed),
            "arms": arms,
            "contrasts": contrasts,
        }
        rows.append(row)
        write_json(progress_path, {"config": config, "rows": rows})
        print(json.dumps({
            "case_id": case_id,
            "completed": len(rows),
            "scores": {arm: arms[arm]["score"] for arm in ARMS},
        }, ensure_ascii=False), flush=True)
    report = {
        "config": config,
        "complete": len(rows) == 26,
        "summary": summarize(rows),
        "rows": rows,
        "production_enabled": False,
        "platform_score": None,
    }
    write_json(args.output, report)
    print(json.dumps({"complete": report["complete"], "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

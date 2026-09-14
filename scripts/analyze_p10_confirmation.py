#!/usr/bin/env python3
"""Strict audit and statistical qualification for frozen P10 confirmation."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.run_p10_combined_confirmation import (
    ARCHIVES, EXPERIMENT_MODULES, PROTOCOL, digest, json_digest, source_snapshot,
)
from starnet.experiments.p10_confirmation_seeds import (
    CONFIRMATION_REPETITIONS, FAMILIES, STRATA, seed_payload,
)
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.cmg import PredictiveState
from starnet.policy.fast_settlement_experiment import FastComponentSettlement
from starnet.policy.public_response_mixture import PublicResponseMixtureLedger


PRIMARY = "candidate_vs_p9"
SECONDARY = "candidate_vs_official_best"
ARMS = ("candidate", "p9_archive", "official_best_archive")
_SETTLEMENT = FastComponentSettlement()


def _expected_scans(seed):
    neighbors = {int(node["id"]): [] for node in seed["nodes"]}
    for left, right in seed["edges"]:
        neighbors[int(left)].append(int(right))
        neighbors[int(right)].append(int(left))
    return {
        int(node["id"]): {
            "w": float(node["w"]), "persona": str(node["persona"]),
            "comm_left": int(node["comm_left"]),
            "neighbors": sorted(neighbors[int(node["id"])]),
        }
        for node in seed["nodes"]
    }


def _action_payload(action):
    return {
        "kind": action.kind, "target_node_1": action.target_node_1,
        "target_node_2": action.target_node_2, "prompt_id": action.prompt_id,
    }


def audit_episode(result, seed):
    """Rebuild one arm from its public action log and frozen hidden seed."""
    records = result.get("action_log")
    if not isinstance(records, list) or result.get("action_log_sha256") != json_digest(records):
        raise ValueError("missing or incorrect action-log hash")
    deltas = result.get("host_action_deltas")
    if (not isinstance(deltas, list) or len(deltas) != result.get("host_calls")
            or any(delta not in (0, 1) for delta in deltas)
            or sum(deltas) != len(records)
            or result.get("max_actions_per_host_step") != max(deltas, default=0)
            or result.get("one_action_per_host_step") is not True):
        raise ValueError("one-action-per-host-step evidence is incomplete")
    record_index = 0
    host_steps = result.get("host_steps", [])
    if len(host_steps) != result.get("host_calls"):
        raise ValueError("host-step evidence length mismatch")
    for host_call, step in enumerate(host_steps, 1):
        if (step.get("host_call") != host_call
                or step.get("action_delta") != deltas[host_call - 1]):
            raise ValueError("host-step sequence mismatch")
        if step["action_delta"] == 1:
            if step.get("action") != records[record_index]:
                raise ValueError("host step does not bind its public action")
            record_index += 1
        elif step.get("action") is not None:
            raise ValueError("action-free host step contains an action")
    if record_index != len(records):
        raise ValueError("host steps do not cover the action log")
    if (len(records) != result.get("action_attempts") or len(records) > 120
            or result.get("host_calls", 121) > 120 or result.get("llm_calls", 121) > 120
            or result.get("action_failures") != 0 or result.get("p8_planning_errors") != 0
            or result.get("p10_planning_errors") != 0
            or result.get("p10_prefix_failures") != 0
            or result.get("p10_response_disabled") is True):
        raise ValueError("action, planner, LLM, or response resource violation")
    accepted = result.get("llm_accepted")
    fallbacks = result.get("llm_fallbacks")
    accepted = 0 if accepted is None else int(accepted)
    fallbacks = 0 if fallbacks is None else int(fallbacks)
    if (accepted + fallbacks != result["llm_calls"]
            or len(result.get("model_decisions", [])) != result["llm_calls"]):
        raise ValueError("inconsistent LLM accounting")
    board = Blackboard(node_count=50)
    budget = float(seed["global_setting"]["max_budget"])
    expected_scans = _expected_scans(seed)
    seed_nodes = {int(node["id"]): node for node in seed["nodes"]}
    prompts = {int(key): float(value) for key, value in seed["prompts"].items()}
    response_ledger = PublicResponseMixtureLedger()
    for index, record in enumerate(records, 1):
        if record.get("index") != index or record.get("success") is not True:
            raise ValueError("nonsequential or unsuccessful action record")
        action = Action(
            record["kind"], record["target_node_1"],
            target_node_2=record.get("target_node_2"), prompt_id=record.get("prompt_id"),
        )
        if not is_legal_action(action, board, budget):
            raise ValueError("recorded action is illegal on reconstructed state")
        if abs(float(record["budget_before"]) - budget) > 1e-8:
            raise ValueError("budget-before mismatch")
        response = record["public_result"]
        if action.kind == "scan":
            if index > 50 or response != expected_scans.get(action.target_node_1):
                raise ValueError("scan order or public seed facts mismatch")
            success = board.record_scan(action.target_node_1, response)
        elif action.kind == "comm":
            node = board.nodes[action.target_node_1]
            before, persona = float(node.w), node.persona
            turn = 4 - int(node.comm_left or 0)
            multiplier = {1: 1.0, 2: 0.5, 3: 0.25}.get(turn)
            hidden = seed_nodes[action.target_node_1]
            expected = max(-100.0, min(
                100.0,
                before + prompts[action.prompt_id] * float(hidden["r"]) * multiplier,
            ))
            new_w = float(response["new_w"])
            if response.get("status") != "success" or abs(new_w - expected) > 1e-8:
                raise ValueError("communication does not match clipped seed response")
            success = board.record_communication(action.target_node_1, response)
            if turn == 1:
                response_ledger.observe_first(persona, before, new_w)
        elif action.kind == "cut":
            if response is not True:
                raise ValueError("cut result mismatch")
            success = board.record_cut(action.target_node_1, action.target_node_2, response)
        else:
            if response is not True:
                raise ValueError("shield result mismatch")
            success = board.record_shield(action.target_node_1, response)
        if not success:
            raise ValueError("public history could not be reconstructed")
        budget -= action_cost(action)
        if abs(float(record["budget_after"]) - budget) > 1e-8:
            raise ValueError("budget-after mismatch")
    if len(board.scanned_ids) != 50 or any(record["kind"] != "scan" for record in records[:50]):
        raise ValueError("episode did not complete all scans before interventions")
    score = float(_SETTLEMENT.score(PredictiveState.from_blackboard(board)))
    if (not math.isfinite(float(result["score"]))
            or abs(score - float(result["score"])) > 1e-8
            or abs(budget - float(result["remaining_budget"])) > 1e-8
            or budget < -1e-8):
        raise ValueError("terminal score or remaining budget mismatch")
    return response_ledger


def audit_candidate_runtime(result, ledger):
    if (result.get("variant") != "combined"
            or result.get("p10_experiment_mode") != "combined"
            or result.get("controller_type") != "P10RuntimeController"
            or result.get("effective_p8_mode") != "conservative"
            or result.get("p10_searches") != 1
            or result.get("p10_search_completed") is not True
            or result.get("p10_pending_count") != 0
            or result.get("p10_last_planning_error") is not None
            or result.get("p8_last_planning_error") is not None
            or result.get("p10_response_disable_reason") is not None):
        raise ValueError("candidate mode or single-search evidence mismatch")
    plan = result.get("p10_plan")
    decision = result.get("p10_plan_decision")
    plan_id = result.get("p10_plan_id")
    approved = int(result.get("p10_approved_plans", 0))
    completed = int(result.get("p10_prefix_completed", 0))
    successes = int(result.get("p10_prefix_successes", 0))
    if approved not in (0, 1) or completed not in (0, 1):
        raise ValueError("invalid plan approval counters")
    selected_plan = [item for item in result.get("model_decisions", [])
                     if item.get("selected_candidate_id") == plan_id]
    if plan_id is not None and (
        not isinstance(plan, dict) or not isinstance(decision, dict)
        or decision.get("accepted") is not True
    ):
        raise ValueError("exposed plan lacks accepted planning evidence")
    if approved:
        if (not isinstance(plan, dict) or not isinstance(decision, dict)
                or decision.get("accepted") is not True or len(selected_plan) != 1):
            raise ValueError("plan approval lacks matching model decision")
        prefix = plan.get("structure_actions")
        if (not isinstance(prefix, list) or not prefix
                or completed != 1 or successes != len(prefix)):
            raise ValueError("approved prefix completion counters mismatch")
        interventions = result["action_log"][50:50 + len(prefix)]
        actual = [{key: record.get(key) for key in
                   ("kind", "target_node_1", "target_node_2", "prompt_id")}
                  for record in interventions]
        if actual != prefix:
            raise ValueError("approved structure prefix was not executed exactly")
    elif selected_plan or completed or successes:
        raise ValueError("unapproved plan executed prefix actions")

    for item in result.get("model_decisions", []):
        ids = item.get("candidate_ids", [])
        if any(candidate_id.startswith("p10-plan:") for candidate_id in ids):
            if plan_id not in ids or item.get("mode") != "single_action":
                raise ValueError("P10 model decision payload is incomplete")
            reasons = item.get("candidate_reasons", {})
            kinds = {}
            for candidate_id in ids:
                reason = str(reasons.get(candidate_id, ""))
                if candidate_id.startswith("p10-plan:"):
                    kinds[candidate_id] = "p10_terminal"
                elif candidate_id.startswith("p8:"):
                    kinds[candidate_id] = "p8_terminal"
                elif reason.startswith("PG REFERENCE:"):
                    kinds[candidate_id] = "pg_reference"
                else:
                    raise ValueError("immediate candidate leaked into terminal comparison")
            budget = float(item["budget"])
            for candidate_id, score in item["candidate_scores"].items():
                roi = float(item["candidate_rois"][candidate_id])
                if kinds[candidate_id] == "pg_reference":
                    if abs(float(score)) > 1e-8 or abs(roi) > 1e-8:
                        raise ValueError("PG reference is not zero")
                elif abs(roi - float(score) / budget) > 1e-8:
                    raise ValueError("terminal alternative ROI basis mismatch")

    activation = result.get("p10_response_activation")
    if activation != ledger.activation:
        raise ValueError("response activation does not match public replay")
    final_weights = result.get("p10_response_final_weights")
    if final_weights is None or any(
        abs(float(final_weights[name]) - ledger.weights()[name]) > 1e-10
        for name in ledger.weights()
    ):
        raise ValueError("response posterior does not match public replay")
    if (result.get("p10_response_accepted") != ledger.accepted
            or result.get("p10_response_censored") != ledger.censored):
        raise ValueError("response observation accounting mismatch")
    switches = int(result.get("p10_response_switches", 0))
    if (activation is None and switches != 0) or (activation is not None and switches <= 0):
        raise ValueError("response gate switch does not match activation")


def paired_metric(rows, comparison):
    values = [float(row["paired_deltas"][comparison]) for row in rows]
    return {
        "cases": len(values), "mean": statistics.fmean(values),
        "minimum": min(values), "maximum": max(values),
        "win_tie_loss": [sum(value > 1e-8 for value in values),
                         sum(abs(value) <= 1e-8 for value in values),
                         sum(value < -1e-8 for value in values)],
        "losses": [{"family": row["family"], "repetition": row["repetition"],
                    "stratum": row["stratum"], "delta": value}
                   for row, value in zip(rows, values) if value < -1e-8],
    }


def block_bootstrap(rows, comparison, draws=10000):
    blocks = {
        (family, repetition): statistics.fmean(
            row["paired_deltas"][comparison] for row in rows
            if row["family"] == family and row["repetition"] == repetition
        )
        for family in FAMILIES for repetition in CONFIRMATION_REPETITIONS
    }
    rng = random.Random(20260914)
    samples = sorted(
        statistics.fmean(
            blocks[family, rng.choice(CONFIRMATION_REPETITIONS)]
            for family in FAMILIES for _ in CONFIRMATION_REPETITIONS
        )
        for _ in range(draws)
    )
    return [samples[int(0.025 * draws)], samples[int(0.975 * draws)]]


def statistical_gate(rows):
    primary = paired_metric(rows, PRIMARY)
    ci = block_bootstrap(rows, PRIMARY)
    by_stratum = {stratum: paired_metric(
        [row for row in rows if row["stratum"] == stratum], PRIMARY,
    ) for stratum in STRATA}
    by_family = {family: paired_metric(
        [row for row in rows if row["family"] == family], PRIMARY,
    ) for family in FAMILIES}
    positive_families = sum(item["mean"] > 1e-8 for item in by_family.values())
    passed = (
        primary["mean"] > 0.0 and ci[0] > 0.0
        and all(item["mean"] >= -1e-8 for item in by_stratum.values())
        and positive_families >= 2
    )
    return passed, primary, ci, by_stratum, by_family, positive_families


def _layered(rows, comparison):
    return {
        "overall": paired_metric(rows, comparison),
        "by_stratum": {stratum: paired_metric(
            [row for row in rows if row["stratum"] == stratum], comparison,
        ) for stratum in STRATA},
        "by_family": {family: paired_metric(
            [row for row in rows if row["family"] == family], comparison,
        ) for family in FAMILIES},
        "by_repetition": {str(repetition): paired_metric(
            [row for row in rows if row["repetition"] == repetition], comparison,
        ) for repetition in CONFIRMATION_REPETITIONS},
    }


def analyze(report):
    config = report.get("config", {})
    expected_snapshot = source_snapshot()
    expected_archives = {
        arm: digest(ROOT / "artifacts/submission" / filename)
        for arm, filename in ARCHIVES.items()
    }
    if (report.get("complete") is not True
            or config.get("protocol_sha256") != digest(PROTOCOL)
            or config.get("runner_sha256") != digest(ROOT / "scripts/run_p10_combined_confirmation.py")
            or config.get("generator_sha256") != digest(ROOT / "src/starnet/experiments/p10_confirmation_seeds.py")
            or config.get("source_snapshot") != expected_snapshot
            or config.get("selected_variant") != "combined"
            or config.get("families") != list(FAMILIES)
            or config.get("strata") != list(STRATA)
            or config.get("repetitions") != list(CONFIRMATION_REPETITIONS)
            or config.get("archive_sha256") != expected_archives):
        raise ValueError("confirmation config or source identity mismatch")
    expected = set(itertools.product(FAMILIES, CONFIRMATION_REPETITIONS, STRATA))
    rows_by_key = {}
    for row in report.get("rows", []):
        key = row.get("family"), row.get("repetition"), row.get("stratum")
        if key not in expected or key in rows_by_key:
            raise ValueError("unexpected or duplicate confirmation row")
        rows_by_key[key] = row
    if set(rows_by_key) != expected:
        raise ValueError(f"incomplete confirmation cohort: {len(rows_by_key)}/48")
    rows = [rows_by_key[key] for key in sorted(expected)]
    for row in rows:
        seed = seed_payload(
            row["family"], row["repetition"], row["stratum"],
            allow_confirmation=True,
        )
        if row.get("seed_sha256") != json_digest(seed) or set(row.get("arms", {})) != set(ARMS):
            raise ValueError("row seed or arm identity mismatch")
        for arm in ARMS:
            result = row["arms"][arm]
            ledger = audit_episode(result, seed)
            if arm == "candidate":
                if result.get("source_snapshot") != expected_snapshot:
                    raise ValueError("candidate per-case source snapshot mismatch")
                audit_candidate_runtime(result, ledger)
            else:
                expected_name = ARCHIVES[arm]
                if (result.get("archive") != expected_name
                        or result.get("archive_sha256") != expected_archives[arm]):
                    raise ValueError("per-case archive identity mismatch")
                if arm == "p9_archive" and (
                    result.get("controller_type") != "P8RuntimeController"
                    or result.get("effective_p8_mode") != "conservative"
                ):
                    raise ValueError("P9 archive runtime mode mismatch")
                if arm == "official_best_archive" and result.get("controller_type") != "RuntimeController":
                    raise ValueError("official-best archive runtime mode mismatch")
        differences = {
            PRIMARY: row["arms"]["candidate"]["score"] - row["arms"]["p9_archive"]["score"],
            SECONDARY: row["arms"]["candidate"]["score"] - row["arms"]["official_best_archive"]["score"],
        }
        if set(row.get("paired_deltas", {})) != set(differences):
            raise ValueError("paired comparison set mismatch")
        for name, value in differences.items():
            if abs(float(row["paired_deltas"][name]) - value) > 1e-8:
                raise ValueError("paired delta mismatch")
    passed, primary, ci, by_stratum, by_family, positive_families = statistical_gate(rows)
    return {
        "schema_version": 1,
        "cohort": "p10_confirmation",
        "pairs": 48,
        "protocol_sha256": digest(PROTOCOL),
        "source_snapshot": expected_snapshot,
        "primary_vs_p9": {**primary, "family_block_bootstrap_ci95": ci},
        "primary_by_stratum": by_stratum,
        "primary_by_family": by_family,
        "positive_topology_family_count": positive_families,
        "secondary_vs_official_best": _layered(rows, SECONDARY),
        "statistical_gate_passed": passed,
        "public_history_resource_audit_passed": True,
        "selected_variant": "combined" if passed else None,
        "release_gate_passed": False,
        "release_gate_pending": [
            "sealed entry evidence", "real LLM plan approval and response activation",
            "Python 3.9 FAQ runtime", "final ZIP identity verification",
        ],
        "production_enabled": False,
        "platform_score": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.input.read_text())
    result = analyze(report)
    result["raw_input"] = {"path": str(args.input.resolve().relative_to(ROOT)),
                           "sha256": digest(args.input), "committed": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "pairs": result["pairs"], "primary": result["primary_vs_p9"],
        "statistical_gate_passed": result["statistical_gate_passed"],
        "release_gate_passed": result["release_gate_passed"],
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

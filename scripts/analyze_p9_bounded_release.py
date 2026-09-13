#!/usr/bin/env python3
"""Audit the complete frozen bounded-P8 cohort and its preregistered gate."""
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
from starnet.experiments.p9_distribution_seeds import FAMILIES, SHIFT_STRATA
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.cmg import PredictiveState
from starnet.policy.fast_settlement_experiment import FastComponentSettlement
from starnet.experiments.p9_distribution_seeds import seed_payload
from scripts.build_submission import INLINE_MODULES

PROTOCOL = ROOT / "experiments/manifests/p9-bounded-release-protocol-20260913.json"
PRIMARY = "bounded_source_vs_p8_submitted"
SECONDARY = "bounded_source_vs_official_best_experimental"
ARMS = ("bounded_source", "official_best_experimental", "p8_submitted")
UNCAPPED_SHIFTS = SHIFT_STRATA[:-2]
MECHANISM_REPORT = ROOT / "experiments/reports/p9-response-bounds-probe-20260913.json"
MECHANISM_SOURCE = ROOT / "scripts/probe_response_bounds.py"
SEED_SOURCE = ROOT / "src/starnet/experiments/p9_distribution_seeds.py"
RUNNER_SOURCE = ROOT / "scripts/run_p9_distribution_validation.py"
SIMULATION_SOURCE = ROOT / "scripts/run_local_policy_matrix.py"
ARCHIVE_PATHS = {
    "official_best_experimental": ROOT / "artifacts/submission/starnet-public-greedy-experimental-20260908.zip",
    "p8_submitted": ROOT / "artifacts/submission/starnet-p8-mean-20260913.zip",
}
_SETTLEMENT = FastComponentSettlement()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seed_digest(seed):
    return json_digest(seed)


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


def audit_episode(result, seed=None):
    """Replay only the recorded public facts; reject invalid action histories."""
    node_count = len(seed["nodes"]) if seed is not None else 50
    board = Blackboard(node_count=node_count)
    budget = float(seed["global_setting"]["max_budget"]) if seed is not None else 100.0
    wasted = 0
    records = result["action_log"]
    action_limit = int(seed["global_setting"]["max_api_calls"]) if seed is not None else 120
    reported_log_hash = result.get("action_log_sha256")
    log_hash_mismatch = (
        reported_log_hash != json_digest(records)
        if seed is not None else
        reported_log_hash not in (None, json_digest(records))
    )
    if (len(records) != result["action_attempts"] or len(records) > action_limit
            or log_hash_mismatch):
        raise ValueError("inconsistent or excessive action count")
    if (result["action_failures"] or result.get("p8_planning_errors", 0)
            or result.get("model_calls", 0) > 120
            or result.get("llm_forced_failures", 0) > 120):
        raise ValueError("failed action/planner or resource violation")
    expected_scans = _expected_scans(seed) if seed is not None else None
    seed_nodes = ({int(node["id"]): node for node in seed["nodes"]}
                  if seed is not None else {})
    prompt_values = ({int(key): float(value) for key, value in seed["prompts"].items()}
                     if seed is not None else {})
    for index, record in enumerate(records, 1):
        if record.get("index") != index:
            raise ValueError("nonsequential action-log index")
        action = Action(record["kind"], record["target_node_1"],
                        target_node_2=record["target_node_2"], prompt_id=record["prompt_id"])
        if not record["success"] or not is_legal_action(action, board, budget):
            raise ValueError("illegal or unsuccessful recorded action")
        if abs(record["budget_before"] - budget) > 1e-8:
            raise ValueError("budget before action mismatch")
        response = record["public_result"]
        if action.kind == "scan":
            if expected_scans is not None and response != expected_scans.get(action.target_node_1):
                raise ValueError("scan facts do not match paired seed")
            success = board.record_scan(action.target_node_1, response)
        elif action.kind == "comm":
            old = board.nodes[action.target_node_1].w
            new = float(response["new_w"])
            if not -100.0 <= new <= 100.0:
                raise ValueError("communication return exceeds measured bounds")
            if seed is not None:
                node = board.nodes[action.target_node_1]
                turn = 4 - int(node.comm_left or 0)
                multiplier = {1: 1.0, 2: 0.5, 3: 0.25}.get(turn)
                hidden = seed_nodes[action.target_node_1]
                if multiplier is None or action.prompt_id not in prompt_values:
                    raise ValueError("invalid communication turn or prompt")
                expected = max(-100.0, min(
                    100.0,
                    old + prompt_values[action.prompt_id] * float(hidden["r"]) * multiplier,
                ))
                if response.get("status") != "success" or abs(new - expected) > 1e-8:
                    raise ValueError("communication result does not match paired seed")
            wasted += int(abs(new - old) <= 1e-8)
            success = board.record_communication(action.target_node_1, response)
        elif action.kind == "cut":
            success = board.record_cut(action.target_node_1, action.target_node_2, response)
        else:
            success = board.record_shield(action.target_node_1, response)
        if not success:
            raise ValueError("public history could not be reconstructed")
        budget -= action_cost(action)
        if abs(record["budget_after"] - budget) > 1e-8:
            raise ValueError("budget after action mismatch")
    expected_counts = {
        kind: sum(record["kind"] == kind for record in records)
        for kind in ("scan", "comm", "cut", "shield")
    }
    if ((seed is not None and result.get("action_counts") != expected_counts)
            or (seed is None and result.get("action_counts") not in (None, expected_counts))):
        raise ValueError("incorrect action counts")
    score = float(_SETTLEMENT.score(PredictiveState.from_blackboard(board)))
    if (abs(budget - result["remaining_budget"]) > 1e-8
            or not math.isfinite(result["score"]) or len(board.scanned_ids) != node_count
            or abs(score - float(result["score"])) > 1e-8):
        raise ValueError("incomplete or inconsistent episode")
    return wasted


def audit_mechanism_report(report, *, source_sha256):
    """Verify the complete 2x2 mechanism probe and every chained update."""
    if report.get("public_custom_seed_mechanism_probe") is not True:
        raise ValueError("mechanism report is not a public custom-seed probe")
    if report.get("source_sha256") != source_sha256:
        raise ValueError("mechanism probe source hash mismatch")
    runs = report.get("runs", [])
    axes = {(float(run.get("factor")), int(run.get("prompt_id"))) for run in runs}
    if len(runs) != 4 or axes != {(0.2, 1), (0.2, 3), (1.5, 1), (1.5, 3)}:
        raise ValueError("mechanism probe axes are incomplete")
    initial_by_node = {1: -110.0, 2: -100.0, 3: -99.0, 4: -90.0, 5: 0.0,
                       6: 90.0, 7: 99.0, 8: 100.0, 9: 110.0}
    clipped_observations = 0
    for run in runs:
        factor, prompt_id = float(run["factor"]), int(run["prompt_id"])
        prompt = {1: 15.0, 3: -5.0}[prompt_id]
        probe_seed = {
            "global_setting": {"max_budget": 100.0, "max_api_calls": 120},
            "nodes": [
                {"id": node, "w": value, "persona": "和平", "r": factor, "comm_left": 3}
                for node, value in initial_by_node.items()
            ],
            "edges": [], "original_total": sum(initial_by_node.values()),
            "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
        }
        expected_seed_hash = hashlib.sha256(
            json.dumps(probe_seed, sort_keys=True).encode()
        ).hexdigest()
        if run.get("seed_sha256") != expected_seed_hash:
            raise ValueError("mechanism probe seed hash mismatch")
        observations = run.get("observations", [])
        keys = {(int(item["node"]), int(item["turn"])) for item in observations}
        if len(observations) != 27 or keys != set(itertools.product(range(1, 10), range(1, 4))):
            raise ValueError("mechanism run is not a complete nine-node, three-turn grid")
        previous_by_node = dict(initial_by_node)
        for item in observations:
            node, turn = int(item["node"]), int(item["turn"])
            initial = initial_by_node[node]
            previous = previous_by_node[node]
            if (float(item["initial_w"]) != initial or float(item["scanned_w"]) != initial
                    or abs(float(item["previous_w"]) - previous) > 1e-9):
                raise ValueError("mechanism observation breaks scan or action continuity")
            unbounded = previous + prompt * factor * {1: 1.0, 2: 0.5, 3: 0.25}[turn]
            bounded = max(-100.0, min(100.0, unbounded))
            observed = float(item["response"]["new_w"])
            if (item["response"].get("status") != "success"
                    or abs(float(item["unbounded_prediction"]) - unbounded) > 1e-9
                    or abs(float(item["bounded_prediction"]) - bounded) > 1e-9
                    or abs(float(item["unbounded_error"]) - (observed - unbounded)) > 1e-9
                    or abs(float(item["bounded_error"]) - (observed - bounded)) > 1e-9
                    or abs(observed - bounded) > 1e-9):
                raise ValueError("mechanism observation does not match bounded update")
            clipped_observations += int(abs(unbounded - bounded) > 1e-9)
            previous_by_node[node] = observed
    if clipped_observations == 0:
        raise ValueError("mechanism probe never distinguishes bounded and unbounded models")
    return 108


def audit_uncapped_envelope(seed):
    """Prove every possible three-use prompt path stays strictly within bounds."""
    prompts = [float(value) for value in seed["prompts"].values()]
    for node in seed["nodes"]:
        remaining = int(node["comm_left"])
        first_turn = 4 - remaining
        slots = sum(0.5 ** (turn - 1) for turn in range(first_turn, 4))
        low = float(node["w"]) + min(0.0, min(prompts)) * float(node["r"]) * slots
        high = float(node["w"]) + max(0.0, max(prompts)) * float(node["r"]) * slots
        if low <= -100.0 or high >= 100.0:
            raise ValueError("declared uncapped-equivalent seed can reach an opinion bound")
    return True


def paired_summary(rows, comparison):
    values = [row["paired_deltas"][comparison] for row in rows]
    return {"mean": statistics.fmean(values), "minimum": min(values), "maximum": max(values),
            "win_tie_loss": [sum(x > 1e-8 for x in values), sum(abs(x) <= 1e-8 for x in values), sum(x < -1e-8 for x in values)]}


def block_bootstrap(rows, comparison, repetitions, draws=10000):
    # The seven shifts share a graph and base opinions. They must travel
    # together whenever a graph/repetition is resampled.
    blocks = {(family, repetition): statistics.fmean(
        row["paired_deltas"][comparison] for row in rows
        if row["family"] == family and row["repetition"] == repetition
    ) for family in FAMILIES for repetition in repetitions}
    rng = random.Random(20260913)
    samples = sorted(statistics.fmean(
        blocks[family, rng.choice(repetitions)]
        for family in FAMILIES for _ in repetitions
    ) for _ in range(draws))
    return [samples[int(0.025 * draws)], samples[int(0.975 * draws)]]


def _audit_source_snapshot(snapshot):
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("missing current-source snapshot")
    expected_paths = set(INLINE_MODULES) | {"src/starnet/submission/config.json"}
    expected_paths.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/starnet/submission/prompt").glob("*.txt")
    )
    if set(snapshot) != expected_paths:
        raise ValueError("current-source snapshot has incomplete path coverage")
    for relative, expected in snapshot.items():
        path = ROOT / relative
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"current source no longer matches snapshot: {relative}")


def _audit_config(config, *, confirmation, repetitions, baseline):
    expected = {
        "schema_version": 1,
        "cohort": "bounded_confirmation" if confirmation else "development",
        "declared_repetitions": list(repetitions),
        "families": list(FAMILIES),
        "shift_strata": list(SHIFT_STRATA),
        "arms": list(ARMS),
        "confirmation_opened": confirmation,
        "unused_reserved_repetitions": [1004, 1005],
    }
    if any(config.get(field) != value for field, value in expected.items()):
        raise ValueError("report config does not match the frozen cohort")
    if config.get("coverage_policy_sha256") is not None:
        raise ValueError("coverage arm is outside the bounded release cohort")
    expected_modes = {
        "official_best_experimental": "unchanged archive; LLM disabled by archive",
        "p8_submitted": "unchanged archive; forced LLM exception and deterministic fallback",
        "bounded_source": "current source; forced LLM exception and deterministic fallback",
    }
    if config.get("execution_modes") != expected_modes:
        raise ValueError("unexpected arm execution mode")
    if config.get("seed_generator_sha256") != digest(SEED_SOURCE):
        raise ValueError("seed-generator hash mismatch")
    if config.get("simulation_runner_sha256") != digest(SIMULATION_SOURCE):
        raise ValueError("simulation-runner hash mismatch")
    if config.get("experiment_runner_sha256") != digest(RUNNER_SOURCE):
        raise ValueError("experiment-runner hash mismatch")
    archives = config.get("archive_sha256", {})
    if any(archives.get(arm) != digest(path) for arm, path in ARCHIVE_PATHS.items()):
        raise ValueError("archive hash mismatch")
    mechanism = config.get("mechanism_gate", {})
    expected_report = str(MECHANISM_REPORT.relative_to(ROOT))
    if (mechanism.get("communication_update") !=
            "clip(previous_w + response, -100, 100) after each success"
            or mechanism.get("public_probe_report") != expected_report
            or mechanism.get("public_probe_sha256") != digest(MECHANISM_REPORT)):
        raise ValueError("mechanism-gate identity mismatch")
    _audit_source_snapshot(config.get("current_source_snapshot"))
    for field in ("current_source_snapshot", "seed_generator_sha256", "simulation_runner_sha256",
                  "experiment_runner_sha256", "archive_sha256", "mechanism_gate"):
        if config.get(field) != baseline.get(field):
            raise ValueError("mixed experiment identities")


def analyze(reports, *, confirmation):
    if not reports:
        raise ValueError("at least one report is required")
    repetitions = (1001, 1002, 1003) if confirmation else (901, 902)
    expected = set(itertools.product(FAMILIES, repetitions, SHIFT_STRATA))
    rows_by_key = {}
    snapshot = reports[0]["config"]["current_source_snapshot"]
    mechanism = json.loads(MECHANISM_REPORT.read_text(encoding="utf-8"))
    mechanism_observations = audit_mechanism_report(
        mechanism, source_sha256=digest(MECHANISM_SOURCE),
    )
    baseline_config = reports[0]["config"]
    for report in reports:
        config = report["config"]
        _audit_config(
            config, confirmation=confirmation, repetitions=repetitions,
            baseline=baseline_config,
        )
        for row in report["rows"]:
            key = row["family"], row["repetition"], row["shift_stratum"]
            if key not in expected or key in rows_by_key:
                raise ValueError("unexpected or repeated paired seed")
            rows_by_key[key] = row
    if set(rows_by_key) != expected:
        raise ValueError(f"incomplete cohort: {len(rows_by_key)}/{len(expected)}")
    rows = [rows_by_key[key] for key in sorted(expected)]
    wasted = dict.fromkeys(("bounded_source", "p8_submitted", "official_best_experimental"), 0)
    for row in rows:
        seed = seed_payload(
            row["family"], row["repetition"], row["shift_stratum"],
            allow_confirmation=confirmation,
        )
        if row.get("seed_sha256") != seed_digest(seed):
            raise ValueError("paired seed hash mismatch")
        if set(row.get("arms", {})) != set(ARMS):
            raise ValueError("missing or unexpected release arm")
        scores = {arm: row["arms"][arm]["score"] for arm in ARMS}
        if row.get("paired_scores") != scores:
            raise ValueError("incorrect paired score table")
        expected_runtime = {
            "bounded_source": ("current_source_casevo_forced_llm_exception_fallback",
                               "P8RuntimeController", "conservative"),
            "p8_submitted": ("archive_casevo_forced_llm_exception_fallback",
                             "P8RuntimeController", "conservative"),
            "official_best_experimental": ("archive_casevo_llm_off", "RuntimeController", None),
        }
        for arm in wasted:
            result = row["arms"][arm]
            wasted[arm] += audit_episode(result, seed)
            runtime = (result.get("execution_mode"), result.get("controller_type"),
                       result.get("effective_p8_mode"))
            if runtime != expected_runtime[arm]:
                raise ValueError("per-case runtime identity mismatch")
            if result.get("llm_attempts") != 0 or result.get("llm_transport_errors") != 0:
                raise ValueError("release arm used an unexpected LLM route")
            if arm == "bounded_source" and result["source_snapshot"] != snapshot:
                raise ValueError("per-case source identity mismatch")
            if arm in ARCHIVE_PATHS and (
                result.get("archive") != ARCHIVE_PATHS[arm].name
                or result.get("archive_sha256") != baseline_config["archive_sha256"][arm]
            ):
                raise ValueError("per-case archive identity mismatch")
        expected_deltas = {
            PRIMARY: scores["bounded_source"] - scores["p8_submitted"],
            SECONDARY: scores["bounded_source"] - scores["official_best_experimental"],
            "p8_submitted_vs_official_best_experimental": (
                scores["p8_submitted"] - scores["official_best_experimental"]
            ),
        }
        if set(row.get("paired_deltas", {})) != set(expected_deltas):
            raise ValueError("missing or unexpected paired comparison")
        for comparison, difference in expected_deltas.items():
            if abs(difference - row["paired_deltas"][comparison]) > 1e-8:
                raise ValueError("incorrect paired score")
    primary = paired_summary(rows, PRIMARY)
    ci = block_bootstrap(rows, PRIMARY, repetitions)
    shifts = {shift: paired_summary([row for row in rows if row["shift_stratum"] == shift], PRIMARY)
              for shift in SHIFT_STRATA}
    for row in rows:
        if row["shift_stratum"] in UNCAPPED_SHIFTS:
            audit_uncapped_envelope(seed_payload(
                row["family"], row["repetition"], row["shift_stratum"],
                allow_confirmation=confirmation,
            ))
    uncapped_equivalent = all(abs(row["paired_deltas"][PRIMARY]) <= 1e-8
                             for row in rows if row["shift_stratum"] in UNCAPPED_SHIFTS)
    passed = (confirmation and primary["mean"] > 0 and ci[0] > 0
              and all(group["mean"] >= -1e-8 for group in shifts.values()) and uncapped_equivalent)
    return {
        "protocol_sha256": digest(PROTOCOL), "cohort": "confirmation" if confirmation else "development",
        "pairs": len(rows), "primary": {**primary, "block_bootstrap_ci95": ci},
        "by_shift": shifts,
        "by_family": {family: paired_summary([row for row in rows if row["family"] == family], PRIMARY) for family in FAMILIES},
        "secondary_official_best": paired_summary(rows, SECONDARY),
        "secondary_by_shift": {shift: paired_summary([row for row in rows if row["shift_stratum"] == shift], SECONDARY) for shift in SHIFT_STRATA},
        "zero_delta_communication_calls": wasted,
        "mechanism_observations_audited": mechanism_observations,
        "uncapped_shift_names": list(UNCAPPED_SHIFTS),
        "uncapped_score_equivalence": uncapped_equivalent,
        "public_history_resource_audit_passed": True,
        "statistical_gate_passed": passed,
        "source_snapshot": snapshot,
        "standard_audit": {"reported_policy_hashes": {"bounded": snapshot["src/starnet/policy/p8_experiment.py"]}},
        "selected_variant": "conservative" if passed else None,
        # This analysis alone does not attest generated ZIP or real LLM checks.
        "variants": {"conservative": {"mean_score_gate_passed": passed}},
        "release_gate_pending": "generated ZIP, real LLM route, and target-interpreter checks",
        "platform_score": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--confirmation", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze([json.loads(path.read_text()) for path in args.inputs], confirmation=args.confirmation)
    result["input_sha256"] = {str(path): digest(path) for path in args.inputs}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("pairs", "primary", "zero_delta_communication_calls", "statistical_gate_passed")}), flush=True)


if __name__ == "__main__":
    main()

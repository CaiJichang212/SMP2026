#!/usr/bin/env python3
"""Select and gate a frozen V1 calibration profile from offline JSONL only.

The runner that collects data is intentionally separate from this script: it
may call ``trigger_eval`` during controlled offline experiments, whereas this
module and the submission never do.  Input rows carry a public Blackboard
snapshot before the action, its action payload, final score, terminal hash and
the preassigned ``split`` (calibration/selection/gate).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping

from starnet.model.blackboard import Blackboard, NodeState
from starnet.policy.actions import Action
from starnet.policy.calibration import CalibrationProfile, canonical_hash
from starnet.policy.cmg import PredictiveState, SettlementPredictor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "experiments" / "manifests" / "v1-calibration.json"

RHO_GRID = (0.0, 0.5, 1.0, 2.0)
GAMMA_GRID = (0.0, 1.0)
A_GRID = (0.1, 0.25, 0.5, 0.75)
B_GRID = (0.0, 0.25, 0.5)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"invalid JSONL line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"JSONL line {line_number} must be an object")
        rows.append(row)
    return rows


def board_from_snapshot(snapshot: Mapping[str, Any]) -> Blackboard:
    board = Blackboard()
    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    dead = snapshot.get("dead_nodes", [])
    if not isinstance(nodes, Mapping) or not isinstance(edges, list) or not isinstance(dead, list):
        raise ValueError("invalid blackboard snapshot")
    for raw_id, state in nodes.items():
        node_id = int(raw_id)
        if not isinstance(state, Mapping):
            raise ValueError("invalid node snapshot")
        board.nodes[node_id] = NodeState(float(state["w"]), str(state["persona"]), state.get("comm_left"))
    board.edges = {tuple(sorted((int(edge[0]), int(edge[1])))) for edge in edges if isinstance(edge, list) and len(edge) == 2}
    board.dead_nodes = {int(node) for node in dead}
    return board


def action_from_row(row: Mapping[str, Any]) -> Action:
    raw = row.get("action")
    if not isinstance(raw, Mapping):
        raise ValueError("settlement row requires action")
    return Action(str(raw["kind"]), int(raw["target_node_1"]), raw.get("target_node_2"), raw.get("prompt_id"))


def is_control_row(row: Mapping[str, Any]) -> bool:
    """Controls score the scanned terminal state without a hypothetical action."""
    raw = row.get("action")
    return isinstance(raw, Mapping) and raw.get("kind") == "control"


def score_for_row(row: Mapping[str, Any], profile: CalibrationProfile) -> float:
    board = board_from_snapshot(row["before_snapshot"])
    state = PredictiveState.from_blackboard(board)
    if is_control_row(row):
        return SettlementPredictor(profile).score(state)
    action = action_from_row(row)
    delta = row.get("observed_delta", 0.0) if action.kind == "comm" else None
    after = state.apply(action, float(delta) if delta is not None else None)
    return SettlementPredictor(profile).score(after)


def _score(row: Mapping[str, Any]) -> float:
    value = row.get("final_score")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("settlement row requires finite final_score")
    return float(value)


def mae(rows: Iterable[Mapping[str, Any]], profile: CalibrationProfile) -> float:
    errors = [abs(score_for_row(row, profile) - _score(row)) for row in rows]
    return statistics.fmean(errors) if errors else math.inf


def spearman(expected: list[float], actual: list[float]) -> float:
    if len(expected) < 2 or len(expected) != len(actual):
        return math.nan
    def ranks(values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda item: item[1])
        output = [0.0] * len(values)
        start = 0
        while start < len(indexed):
            end = start + 1
            while end < len(indexed) and indexed[end][1] == indexed[start][1]:
                end += 1
            rank = (start + end - 1) / 2 + 1
            for index, _ in indexed[start:end]:
                output[index] = rank
            start = end
        return output
    left, right = ranks(expected), ranks(actual)
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(sum((x - left_mean) ** 2 for x in left) * sum((y - right_mean) ** 2 for y in right))
    return numerator / denominator if denominator else math.nan


def profile_grid() -> list[CalibrationProfile]:
    profiles = [CalibrationProfile(False, model="degree")]
    profiles += [CalibrationProfile(False, model="degroot", rho=rho, gamma=gamma) for rho in RHO_GRID for gamma in GAMMA_GRID]
    profiles += [CalibrationProfile(False, model="friedkin_johnsen", rho=rho, gamma=gamma, a=a, b=b) for rho in RHO_GRID for gamma in GAMMA_GRID for a in A_GRID for b in B_GRID]
    return profiles


def split_rows(rows: Iterable[Mapping[str, Any]], split: str) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get("split") == split and row.get("kind", "settlement") == "settlement"]


def _median_graph_normalized_mae(rows: Iterable[Mapping[str, Any]], profile: CalibrationProfile) -> float:
    by_graph: dict[str, list[float]] = {}
    for row in rows:
        score = _score(row)
        prediction = score_for_row(row, profile)
        graph = str(row.get("graph_id", "unknown"))
        by_graph.setdefault(graph, []).append(abs(prediction - score) / max(1.0, abs(score)))
    return statistics.median(statistics.fmean(errors) for errors in by_graph.values()) if by_graph else math.inf


def response_statistics(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, float], dict[str, float]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        if row.get("kind") != "response" or not row.get("success"):
            continue
        key = CalibrationProfile.response_key(str(row["persona"]), int(row.get("prompt_id", 1)), int(row["turn"]))
        delta = row.get("delta_w")
        if isinstance(delta, (int, float)) and not isinstance(delta, bool) and math.isfinite(delta):
            grouped.setdefault(key, []).append(float(delta))
    means = {key: statistics.fmean(values) for key, values in grouped.items()}
    stds = {key: statistics.pstdev(values) if len(values) > 1 else 0.0 for key, values in grouped.items()}
    return means, stds


def required_response_keys(manifest: Mapping[str, Any]) -> set[str]:
    """Validate the preregistered persona/prompt/round table before enabling CMG."""
    protocol = manifest.get("response_protocol")
    if not isinstance(protocol, Mapping):
        return set()
    personas = protocol.get("personas")
    prompts = protocol.get("prompt_ids")
    turns = protocol.get("communications_per_session")
    if not isinstance(personas, list) or not isinstance(prompts, list) or not isinstance(turns, int) or turns <= 0:
        return set()
    return {
        CalibrationProfile.response_key(str(persona), int(prompt_id), turn)
        for persona in personas
        for prompt_id in prompts
        for turn in range(1, turns + 1)
    }


def build_report(manifest: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    calibration, selection, gate = (split_rows(rows, name) for name in ("calibration", "selection", "gate"))
    if not calibration or not selection or not gate:
        return {"gate_passed": False, "reason": "missing_required_split"}
    tuned_by_model = {
        model: min(
            (candidate for candidate in profile_grid() if candidate.model == model),
            key=lambda candidate: (mae(calibration, candidate), candidate.computed_hash()),
        )
        for model in ("degree", "degroot", "friedkin_johnsen")
    }
    # Calibration tunes each family.  Selection can choose only among those
    # frozen candidates and does not inspect the gate split.
    selected = max(
        tuned_by_model.values(),
        key=lambda candidate: (
            -math.inf if math.isnan(spearman([score_for_row(row, candidate) for row in selection], [_score(row) for row in selection]))
            else spearman([score_for_row(row, candidate) for row in selection], [_score(row) for row in selection]),
            candidate.computed_hash(),
        ),
    )
    candidate_models = {
        model: {
            "parameters": {
                "rho": candidate.rho,
                "gamma": candidate.gamma,
                "a": candidate.a,
                "b": candidate.b,
            },
            "calibration_mae": mae(calibration, candidate),
            "selection_spearman": spearman(
                [score_for_row(row, candidate) for row in selection],
                [_score(row) for row in selection],
            ),
        }
        for model, candidate in tuned_by_model.items()
    }
    actual = [_score(row) for row in gate]
    predicted = [score_for_row(row, selected) for row in gate]
    ordering = spearman(predicted, actual)
    normalized_mae = _median_graph_normalized_mae(gate, selected)
    terminal_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in gate:
        terminal_groups.setdefault((str(row.get("terminal_hash")), str(row.get("graph_id"))), []).append(row)
    deterministic = bool(terminal_groups)
    for group in terminal_groups.values():
        scores = [_score(row) for row in group]
        deterministic &= len(group) >= 5 and max(scores) - min(scores) <= 0.02 * max(1.0, abs(statistics.fmean(scores)))
    means, stds = response_statistics(rows)
    residuals: dict[str, float] = {}
    residual_coverage = True
    for kind in ("comm", "cut", "shield"):
        errors = [
            score_for_row(row, selected) - _score(row)
            for row in calibration + selection
            if not is_control_row(row) and action_from_row(row).kind == kind
        ]
        # A failed report must still be serialisable as an explicitly
        # unverified profile; never encode infinity into a frozen payload.
        residuals[kind] = statistics.pstdev(errors) if errors else 0.0
        residual_coverage &= bool(errors)
    manifest_hash, data_hash = canonical_hash(manifest), canonical_hash(rows)
    required_keys = required_response_keys(manifest)
    response_coverage = bool(required_keys and required_keys.issubset(means) and required_keys.issubset(stds))
    criteria_passed = bool(
        ordering >= 0.90
        and normalized_mae <= 0.05
        and deterministic
        and response_coverage
        and residual_coverage
    )
    provisional = CalibrationProfile(
        criteria_passed,
        selected.model,
        selected.rho,
        selected.gamma,
        selected.a,
        selected.b,
        residuals,
        means,
        stds,
        manifest_hash,
        data_hash,
    )
    profile = CalibrationProfile(**{**asdict(provisional), "profile_hash": provisional.computed_hash()})
    passed = bool(criteria_passed and profile.verified)
    return {
        "gate_passed": passed,
        "winner": asdict(profile),
        "gate": {
            "spearman": ordering,
            "median_normalized_mae": normalized_mae,
            "terminal_deterministic": deterministic,
            "response_prior_coverage": response_coverage,
            "settlement_residual_coverage": residual_coverage,
            "missing_response_keys": sorted(required_keys.difference(means) | required_keys.difference(stds)),
        },
        "selection_model": selected.model,
        "candidate_models": candidate_models,
        "manifest_hash": manifest_hash,
        "data_hash": data_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("manifest must be an object")
    report = build_report(manifest, load_jsonl(args.results))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"gate_passed={report['gate_passed']} report={args.report}")
    return 0 if report["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

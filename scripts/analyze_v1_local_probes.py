#!/usr/bin/env python3
"""Analyse preregistered V1 local mechanism probes without ranking policies.

The local probes are controlled, custom-seed mechanism experiments.  This
tool deliberately treats a transport/protocol problem as missing data: a row
with an exception, failed action, mismatched scan, or missing finite score
cannot contribute to a mechanism conclusion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "experiments" / "manifests" / "v1-local-probes.json"


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row {line_number} must be an object")
        rows.append(row)
    return rows


def finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def row_is_comparable(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("comparable") is True
        and row.get("protocol_error") is None
        and row.get("action_failures", 0) == 0
        and row.get("scan_snapshot_match") is True
        and finite_number(row.get("final_score"))
    )


def _communication_deltas(row: Mapping[str, Any], probe: Mapping[str, Any]) -> list[float]:
    """Recover observed communication deltas from public action feedback."""
    seed = probe.get("seed")
    outcomes = row.get("action_outcomes")
    if not isinstance(seed, Mapping) or not isinstance(outcomes, list):
        return []
    current = {
        item.get("id"): float(item["w"])
        for item in seed.get("nodes", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), int) and finite_number(item.get("w"))
    }
    deltas: list[float] = []
    for outcome in outcomes:
        if not isinstance(outcome, Mapping) or not outcome.get("succeeded"):
            continue
        action, response = outcome.get("action"), outcome.get("raw_response")
        if not isinstance(action, Mapping) or action.get("kind") != "comm" or not isinstance(response, Mapping):
            continue
        node_id, new_w = action.get("target_node_1"), response.get("new_w")
        if not isinstance(node_id, int) or node_id not in current or not finite_number(new_w):
            continue
        deltas.append(float(new_w) - current[node_id])
        current[node_id] = float(new_w)
    return deltas


def _score(rows_by_probe: Mapping[str, Mapping[str, Any]], probe_id: str) -> float | None:
    row = rows_by_probe.get(probe_id)
    score = row.get("final_score") if row is not None else None
    return float(score) if finite_number(score) else None


def mechanism_metrics(
    rows_by_probe: Mapping[str, Mapping[str, Any]], probes_by_id: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    """Derive only the effects explicitly identified by the 10-probe manifest."""
    isolated_control = _score(rows_by_probe, "isolated_p1_x0")
    bridge_control = _score(rows_by_probe, "bridge_control")
    required = {
        "isolated_p1_x0", "isolated_p1_x1", "isolated_p1_x2", "isolated_p1_x3", "isolated_p2_x1",
        "bridge_control", "bridge_comm_p1", "bridge_cut", "bridge_shield", "bridge_shield_comm_p1",
    }
    if isolated_control is None or bridge_control is None or not required.issubset(rows_by_probe):
        return None
    scores = {probe_id: _score(rows_by_probe, probe_id) for probe_id in sorted(required)}
    if not all(value is not None for value in scores.values()):
        return None
    p1_deltas = _communication_deltas(rows_by_probe["isolated_p1_x3"], probes_by_id["isolated_p1_x3"])
    p1_ratios = [delta / p1_deltas[0] for delta in p1_deltas[1:]] if p1_deltas and p1_deltas[0] else []
    return {
        "isolated_scores": {key: scores[key] for key in sorted(key for key in required if key.startswith("isolated"))},
        "isolated_delta_vs_control": {
            key: round(float(scores[key] - isolated_control), 6)
            for key in ("isolated_p1_x1", "isolated_p1_x2", "isolated_p1_x3", "isolated_p2_x1")
        },
        "observed_p1_successive_deltas": [round(value, 6) for value in p1_deltas],
        "observed_p1_decay_ratios_to_first": [round(value, 6) for value in p1_ratios],
        "bridge_scores": {key: scores[key] for key in sorted(key for key in required if key.startswith("bridge"))},
        "bridge_delta_vs_control": {
            key: round(float(scores[key] - bridge_control), 6)
            for key in ("bridge_comm_p1", "bridge_cut", "bridge_shield", "bridge_shield_comm_p1")
        },
    }


def summarize(manifest: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    probes = manifest.get("probes")
    if not isinstance(probes, list):
        raise ValueError("manifest must contain probes")
    probes_by_id = {
        probe.get("id"): probe
        for probe in probes
        if isinstance(probe, Mapping) and isinstance(probe.get("id"), str)
    }
    if len(probes_by_id) != len(probes):
        raise ValueError("each manifest probe requires a unique string id")
    plan_hash = canonical_hash(manifest)
    rows_by_probe: dict[str, Mapping[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        probe_id = row.get("probe_id")
        if not isinstance(probe_id, str):
            continue
        if probe_id in rows_by_probe:
            duplicates.append(probe_id)
        rows_by_probe[probe_id] = row
    expected = set(probes_by_id)
    observed = set(rows_by_probe)
    comparable_ids = sorted(probe_id for probe_id, row in rows_by_probe.items() if row_is_comparable(row))
    error_counts: dict[str, int] = {}
    error_detail_counts: dict[str, int] = {}
    invalid_reasons: dict[str, list[str]] = {}
    for probe_id, row in rows_by_probe.items():
        reasons: list[str] = []
        if row.get("plan_hash") != plan_hash:
            reasons.append("plan_hash_mismatch")
        if row.get("protocol_error") is not None:
            error = str(row.get("protocol_error"))
            error_counts[error] = error_counts.get(error, 0) + 1
            detail = row.get("protocol_error_detail")
            if isinstance(detail, str) and detail:
                error_detail_counts[detail] = error_detail_counts.get(detail, 0) + 1
            reasons.append(f"protocol_error:{error}")
        if row.get("action_failures", 0) != 0:
            reasons.append("action_failure")
        if row.get("scan_snapshot_match") is not True:
            reasons.append("scan_snapshot_mismatch_or_missing")
        if not finite_number(row.get("final_score")):
            reasons.append("missing_finite_score")
        if row.get("comparable") is not True:
            reasons.append("runner_marked_noncomparable")
        if reasons:
            invalid_reasons[probe_id] = reasons
    complete = observed == expected and not duplicates
    all_comparable = complete and set(comparable_ids) == expected
    metrics = mechanism_metrics(rows_by_probe, probes_by_id) if all_comparable else None
    return {
        "schema_version": 1,
        "experiment": manifest.get("name"),
        "plan_hash": plan_hash,
        "expected_probe_count": len(expected),
        "observed_probe_count": len(observed),
        "comparable_probe_count": len(comparable_ids),
        "missing_probe_ids": sorted(expected.difference(observed)),
        "unexpected_probe_ids": sorted(observed.difference(expected)),
        "duplicate_probe_ids": sorted(set(duplicates)),
        "protocol_error_counts": error_counts,
        "protocol_error_detail_counts": error_detail_counts,
        "invalid_reasons": invalid_reasons,
        "analysis_status": "complete" if all_comparable else "insufficient_noncomparable_data",
        "mechanism_metrics": metrics,
    }


def markdown_report(summary: Mapping[str, Any], *, raw_path: Path) -> str:
    lines = ["# V1 本地机制探针结果", ""]
    lines += [
        f"数据：`{raw_path}`；计划哈希：`{str(summary['plan_hash'])[:16]}`。",
        "",
        "| 指标 | 值 |",
        "| --- | ---: |",
        f"| 预注册 probe | {summary['expected_probe_count']} |",
        f"| 已观测 probe | {summary['observed_probe_count']} |",
        f"| 可比较 probe | {summary['comparable_probe_count']} |",
        "",
    ]
    if summary["analysis_status"] != "complete":
        lines += ["## 结果无效（不作机制结论）", ""]
        errors = summary.get("protocol_error_counts", {})
        if errors:
            lines += ["协议异常：", ""]
            for name, count in sorted(errors.items()):
                lines.append(f"- `{name}`：{count}")
            lines.append("")
        details = summary.get("protocol_error_detail_counts", {})
        if isinstance(details, Mapping) and details:
            lines += ["安全诊断（不含响应正文或凭据）：", ""]
            for detail, count in sorted(details.items()):
                lines.append(f"- `{detail}`：{count}")
            lines.append("")
        lines += [
            "本批记录没有满足预注册可比性条件的完整数据。不得用空值、异常响应或历史分数补齐；"
            "应在官方调试服务恢复后，以相同 manifest 创建新 session 复跑。",
            "",
        ]
        return "\n".join(lines)
    metrics = summary["mechanism_metrics"]
    assert isinstance(metrics, Mapping)
    lines += ["## 孤立节点：游说响应", "", "| probe | 最终分 | 相对不游说 Δ |"]
    lines.append("| --- | ---: | ---: |")
    isolated_scores = metrics["isolated_scores"]
    isolated_deltas = metrics["isolated_delta_vs_control"]
    for probe_id, score in isolated_scores.items():
        delta = 0.0 if probe_id == "isolated_p1_x0" else isolated_deltas[probe_id]
        lines.append(f"| {probe_id} | {score:.3f} | {delta:+.3f} |")
    lines += ["", f"`prompt=1` 连续三次实际 Δw：{metrics['observed_p1_successive_deltas']}；相对首次比例：{metrics['observed_p1_decay_ratios_to_first']}。", ""]
    lines += ["## 两节点负面桥：动作结算", "", "| probe | 最终分 | 相对对照 Δ |", "| --- | ---: | ---: |"]
    bridge_scores = metrics["bridge_scores"]
    bridge_deltas = metrics["bridge_delta_vs_control"]
    for probe_id, score in bridge_scores.items():
        delta = 0.0 if probe_id == "bridge_control" else bridge_deltas[probe_id]
        lines.append(f"| {probe_id} | {score:.3f} | {delta:+.3f} |")
    lines += [
        "",
        "该结果仅辨识这两个受控小图的局部结算：它不估计隐藏 seed 的平均得分，也不构成 V1 相对 V0 的晋级证据。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("manifest root must be an object")
    summary = summarize(manifest, load_jsonl(args.raw))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(markdown_report(summary, raw_path=args.raw), encoding="utf-8")
    summary_path = args.summary or args.report.with_suffix(".json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"analysis_status={summary['analysis_status']} report={args.report} summary={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

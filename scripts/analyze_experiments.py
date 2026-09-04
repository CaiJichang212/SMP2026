#!/usr/bin/env python3
"""Summarise V0 raw JSONL without selecting a best single remote score."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
from statistics import median
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "experiments" / "manifests" / "v0-matrix.json"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "experiments" / "raw" / "v0-matrix"
DEFAULT_REPORT = PROJECT_ROOT / "experiments" / "reports" / "v0-matrix-summary.md"


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"invalid JSONL line {line_number}") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def bootstrap_mean_ci(seed_means: Mapping[str, float], *, samples: int = 10_000) -> tuple[float, float]:
    values = list(seed_means.values())
    if not values:
        return (math.nan, math.nan)
    rng = random.Random(20260904)
    means = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(samples)]
    return percentile(means, 0.025), percentile(means, 0.975)


def numeric_score(row: Mapping[str, object]) -> float | None:
    score = row.get("final_score")
    return float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None


def _analysis_comparable(row: Mapping[str, object]) -> bool:
    """Defence in depth for legacy/manual results as well as the runner flag."""
    return bool(
        row.get("comparable")
        and row.get("protocol_error") is None
        and row.get("action_failures", 0) == 0
    )


def require_single_main_cohort(rows: Iterable[Mapping[str, object]]) -> tuple[str, str]:
    """Reject a result file that combines stable and unstable (or changed) plans."""
    cohorts = {
        (row.get("plan_hash"), row.get("matrix_branch"))
        for row in rows
        if row.get("phase") == "main"
    }
    if len(cohorts) != 1:
        raise ValueError("results must contain exactly one main experiment plan and branch")
    plan_hash, matrix_branch = cohorts.pop()
    if not isinstance(plan_hash, str) or not plan_hash or matrix_branch not in {"stable", "unstable"}:
        raise ValueError("results lack a valid plan_hash or matrix_branch")
    return plan_hash, matrix_branch


def paired_deltas(rows: Iterable[Mapping[str, object]]) -> dict[str, dict[str, list[float]]]:
    """Return variant -> seed -> replicate-wise deltas against scan_only."""
    by_key: dict[tuple[str, int, str], float] = {}
    for row in rows:
        if row.get("phase") != "main" or not _analysis_comparable(row):
            continue
        score = numeric_score(row)
        repetition = row.get("repetition", 1)
        if score is None or not isinstance(repetition, int):
            continue
        by_key[(str(row.get("seed_id")), repetition, str(row.get("variant")))] = score
    deltas: dict[str, dict[str, list[float]]] = {}
    for (seed, repetition, variant), score in by_key.items():
        baseline = by_key.get((seed, repetition, "scan_only"))
        if baseline is None or variant == "scan_only":
            continue
        deltas.setdefault(variant, {}).setdefault(seed, []).append(score - baseline)
    return deltas


def summarize(rows: Iterable[Mapping[str, object]]) -> dict[str, Any]:
    all_rows = list(rows)
    deltas = paired_deltas(all_rows)
    output: dict[str, Any] = {
        "valid_main_sessions": sum(
            row.get("phase") == "main" and _analysis_comparable(row) for row in all_rows
        ),
        "variants": {},
    }
    for variant, seed_values in sorted(deltas.items()):
        flat = [value for values in seed_values.values() for value in values]
        seed_means = {seed: sum(values) / len(values) for seed, values in seed_values.items()}
        lo, hi = bootstrap_mean_ci(seed_means)
        output["variants"][variant] = {
            "seed_count": len(seed_means),
            "replicate_count": len(flat),
            "mean_delta": sum(flat) / len(flat),
            "median_delta": median(flat),
            "stddev_delta": (sum((value - sum(flat) / len(flat)) ** 2 for value in flat) / len(flat)) ** 0.5,
            "worst_seed_delta": min(seed_means.values()),
            "bootstrap_95_ci": [lo, hi],
            "seed_mean_deltas": seed_means,
        }
    return output


def markdown_report(summary: Mapping[str, object], gate_status: Mapping[str, object] | None) -> str:
    lines = ["# V0 参数实验汇总", ""]
    if gate_status is None:
        lines += ["门禁结果未找到；以下统计不应视为正式策略排名。", ""]
    else:
        lines += [f"可重复性门禁：`stable={gate_status.get('stable')}`。", ""]
    lines += ["主指标为同 seed、同重复下相对 `scan_only` 的得分增量；CI 为按 seed 区组 10,000 次 bootstrap。", ""]
    variants = summary.get("variants", {})
    if not isinstance(variants, Mapping) or not variants:
        lines += ["尚无足够的可比正式 session，未产生参数排名。", ""]
        return "\n".join(lines)
    lines += ["| 变体 | seeds | 均值 Δ | 中位 Δ | 最差 seed | 95% CI |", "| --- | ---: | ---: | ---: | ---: | --- |"]
    for name, data in variants.items():
        if not isinstance(data, Mapping):
            continue
        ci = data["bootstrap_95_ci"]
        lines.append(
            f"| {name} | {data['seed_count']} | {data['mean_delta']:.3f} | {data['median_delta']:.3f} | "
            f"{data['worst_seed_delta']:.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] |"
        )
    lines += ["", "若门禁不稳定或终态哈希相同但分数漂移，所有表项仅表示不确定估计，不能以单次最高分作结论。", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, help="an explicit namespaced branch results.jsonl")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--branch", choices=("stable", "unstable"))
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if args.raw is not None:
        raw_path = args.raw
    else:
        from scripts.run_experiments import result_namespace

        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise SystemExit("manifest root must be an object")
        plan_dir = result_namespace(args.result_dir.resolve(), manifest)
        gate_status = json.loads((plan_dir / "gate_status.json").read_text(encoding="utf-8"))
        if not gate_status.get("gate_complete"):
            raise SystemExit("reproducibility gate is incomplete; refuse to analyse a partial plan")
        branch = args.branch or ("stable" if gate_status.get("stable") else "unstable")
        raw_path = plan_dir / branch / "results.jsonl"
    rows = load_rows(raw_path)
    plan_hash, matrix_branch = require_single_main_cohort(rows)
    summary = summarize(rows)
    summary["plan_hash"] = plan_hash
    summary["matrix_branch"] = matrix_branch
    gate_path = raw_path.parent.parent / "gate_status.json"
    gate_status = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.is_file() else None
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(markdown_report(summary, gate_status), encoding="utf-8")
    summary_path = args.report.with_suffix(".json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.report} and {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

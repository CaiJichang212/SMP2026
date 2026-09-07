#!/usr/bin/env python3
"""Analyse the paired P2.3 B3/B4 versus B1 policy matrix."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
from statistics import median
from typing import Any, Mapping


VARIANTS = ("b1_persuasion", "b3_single_structure", "b4_beam_structure")
COMPARISONS = (
    ("b3_single_structure", "b1_persuasion"),
    ("b4_beam_structure", "b1_persuasion"),
    ("b4_beam_structure", "b3_single_structure"),
)


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _comparable(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("phase") == "main"
        and row.get("comparable") is True
        and row.get("protocol_error") is None
        and row.get("action_failures", 0) == 0
        and isinstance(row.get("final_score"), (int, float))
    )


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _bootstrap(values: list[float], samples: int = 10_000) -> tuple[float, float]:
    rng = random.Random(20260906)
    means = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(samples)]
    return _percentile(means, 0.025), _percentile(means, 0.975)


def analyse(rows: list[dict[str, Any]], *, expected_blocks: int) -> dict[str, Any]:
    by_key: dict[tuple[str, int, str], dict[str, Any]] = {}
    failures = 0
    for row in rows:
        if row.get("phase") != "main":
            continue
        key = (str(row.get("seed_id")), int(row.get("repetition", 0)), str(row.get("variant")))
        if key in by_key:
            raise ValueError(f"duplicate main row {key}")
        by_key[key] = row
        failures += int(not _comparable(row))

    complete_keys = 0
    block_deltas: dict[str, dict[str, float]] = {f"{left}-{right}": {} for left, right in COMPARISONS}
    structure_actions: dict[str, int] = {variant: 0 for variant in VARIANTS}
    for seed_id in sorted({key[0] for key in by_key}):
        repetitions = [1, 2, 3]
        for repetition in repetitions:
            if all((seed_id, repetition, variant) in by_key for variant in VARIANTS):
                complete_keys += 1
        if all(
            (seed_id, repetition, variant) in by_key
            and _comparable(by_key[(seed_id, repetition, variant)])
            for repetition in repetitions for variant in VARIANTS
        ):
            means = {
                variant: sum(float(by_key[(seed_id, repetition, variant)]["final_score"]) for repetition in repetitions) / len(repetitions)
                for variant in VARIANTS
            }
            for left, right in COMPARISONS:
                block_deltas[f"{left}-{right}"][seed_id] = means[left] - means[right]

    # Count only comparable structure actions; a paired comparison must not
    # pass if a structural variant silently fell back to persuasion.
    for variant in ("b3_single_structure", "b4_beam_structure"):
        structure_actions[variant] = sum(
            1 for row in by_key.values()
            if row.get("variant") == variant and _comparable(row)
            and (row.get("action_counts", {}).get("cut", 0) or row.get("action_counts", {}).get("shield", 0))
        )

    comparisons: dict[str, Any] = {}
    for name, values_by_seed in block_deltas.items():
        values = list(values_by_seed.values())
        if not values:
            continue
        ci = _bootstrap(values)
        family: dict[str, list[float]] = {}
        for seed_id, delta in values_by_seed.items():
            family.setdefault(seed_id.rsplit("-", 2)[0], []).append(delta)
        family_means = {family_name: sum(items) / len(items) for family_name, items in family.items()}
        comparisons[name] = {
            "block_count": len(values),
            "mean_delta": sum(values) / len(values),
            "median_delta": median(values),
            "minimum_block_delta": min(values),
            "bootstrap_95_ci": list(ci),
            "family_mean_deltas": family_means,
            "gate_passed": len(values) == expected_blocks and ci[0] > 0 and all(value >= 0 for value in family_means.values()),
        }

    gate_passed = (
        failures == 0
        and len({key[0] for key in by_key}) == expected_blocks
        and complete_keys == expected_blocks * 3
        and all(count == expected_blocks * 3 for count in structure_actions.values())
        and all(item.get("gate_passed") is True for item in comparisons.values())
    )
    return {
        "schema_version": 1,
        "experiment": "p2-b3-b4-vs-b1-paired-policy-matrix",
        "expected_blocks": expected_blocks,
        "main_rows": len(by_key),
        "comparable_failures": failures,
        "complete_seed_repetition_cells": complete_keys,
        "complete_seed_blocks": len(block_deltas["b3_single_structure-b1_persuasion"]),
        "structure_action_rows": structure_actions,
        "comparisons": comparisons,
        "gate_passed": gate_passed,
        "decision": "qualify B3/B4 for further P3 experiments" if gate_passed else "keep B1 default and do not promote structure policy",
    }


def markdown(report: Mapping[str, Any]) -> str:
    lines = ["# P2.3 结构策略配对实验结果", "", f"总门禁：`{report['gate_passed']}`。", ""]
    lines += ["| 对比 | seed block | 均值 Δ | 中位 Δ | 95% CI | 最差拓扑族 | 判定 |", "| --- | ---: | ---: | ---: | --- | ---: | --- |"]
    for name, item in report.get("comparisons", {}).items():
        worst = min(item["family_mean_deltas"].values()) if item.get("family_mean_deltas") else math.nan
        ci = item["bootstrap_95_ci"]
        lines.append(f"| `{name}` | {item['block_count']} | {item['mean_delta']:.3f} | {item['median_delta']:.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] | {worst:.3f} | {item['gate_passed']} |")
    lines += ["", f"可比失败数：`{report['comparable_failures']}`；结构动作记录：`{report['structure_action_rows']}`。", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-blocks", type=int, default=24)
    args = parser.parse_args()
    report = analyse(_rows(args.raw), expected_blocks=args.expected_blocks)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(markdown(report), encoding="utf-8")
    args.report.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.report} and {args.report.with_suffix('.json')}")
    return 0 if report["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

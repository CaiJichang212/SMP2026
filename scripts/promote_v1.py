#!/usr/bin/env python3
"""Refuse or approve the V1 default switch using a fully paired matrix.

This is intentionally conservative: it emits a decision by default.  The
optional ``--apply`` is the explicit, reviewable source mutation that changes
the submission default after both gates have passed.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
from typing import Any, Mapping

# Direct CLI execution places this directory, rather than the repository root,
# on sys.path.  Package imports (tests) need the qualified form instead.
if __package__:
    from scripts.analyze_experiments import load_rows, percentile
else:
    from analyze_experiments import load_rows, percentile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "src" / "starnet" / "policy" / "config.py"


def paired_v1_deltas(rows: list[Mapping[str, Any]]) -> tuple[dict[str, list[float]], list[str]]:
    indexed: dict[tuple[str, str, int, str], Mapping[str, Any]] = {}
    issues: list[str] = []
    cohorts = {
        (row.get("plan_hash"), row.get("matrix_branch"))
        for row in rows
        if row.get("phase") == "main"
    }
    if len(cohorts) != 1:
        issues.append("results must contain exactly one plan_hash/matrix_branch cohort")
    for plan_hash, branch in cohorts:
        if not isinstance(plan_hash, str) or not plan_hash or branch not in {"stable", "unstable"}:
            issues.append("results contain missing or invalid plan_hash/matrix_branch metadata")
    for row in rows:
        if row.get("phase") != "main":
            continue
        key = (str(row.get("plan_hash")), str(row.get("matrix_branch")), int(row.get("repetition", 0)), str(row.get("seed_id")))
        variant = str(row.get("variant"))
        if variant in {"v0_deterministic", "v1_cmg"}:
            indexed[(*key, variant)] = row
    deltas: dict[str, list[float]] = {}
    pairs = {(key[:4]) for key in indexed}
    for key in sorted(pairs):
        v0, v1 = indexed.get((*key, "v0_deterministic")), indexed.get((*key, "v1_cmg"))
        if v0 is None or v1 is None:
            issues.append(f"missing pair {key}")
            continue
        for variant, row in (("v0", v0), ("v1", v1)):
            if not row.get("comparable") or row.get("protocol_error") is not None or row.get("action_failures", 0) != 0:
                issues.append(f"{variant} protocol failure {key}")
        if v1.get("llm_calls") != 0:
            issues.append(f"v1 LLM use {key}")
        left, right = v0.get("final_score"), v1.get("final_score")
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            issues.append(f"non-numeric score {key}")
            continue
        deltas.setdefault(key[3], []).append(float(right) - float(left))
    return deltas, issues


def bootstrap_lower(seed_means: Mapping[str, float], samples: int = 10_000) -> float:
    values = list(seed_means.values())
    if not values:
        return math.nan
    rng = random.Random(20260905)
    means = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(samples)]
    return percentile(means, 0.025)


def decision(calibration_report: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    deltas, issues = paired_v1_deltas(rows)
    seed_means = {seed: sum(values) / len(values) for seed, values in deltas.items() if values}
    lower = bootstrap_lower(seed_means)
    required_seeds = 6
    passed = bool(
        calibration_report.get("gate_passed")
        and len(seed_means) == required_seeds
        and all(len(values) == 3 for values in deltas.values())
        and not issues
        and math.isfinite(lower)
        and lower > 0.0
        and all(value >= 0.0 for value in seed_means.values())
    )
    return {"promoted": passed, "bootstrap_95_ci_lower": lower, "seed_mean_deltas": seed_means, "issues": issues}


def apply_default(config_path: Path) -> None:
    source = config_path.read_text(encoding="utf-8")
    old = "DEFAULT_POLICY_CONFIG = PolicyConfig()"
    new = "DEFAULT_POLICY_CONFIG = PolicyConfig(policy_mode=PolicyMode.V1_CMG)"
    if new in source:
        return
    if old not in source:
        raise RuntimeError("refuse to edit an unrecognised default configuration")
    config_path.write_text(source.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-report", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = json.loads(args.calibration_report.read_text(encoding="utf-8"))
    outcome = decision(report, load_rows(args.results))
    args.decision.parent.mkdir(parents=True, exist_ok=True)
    args.decision.write_text(json.dumps(outcome, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.apply and outcome["promoted"]:
        apply_default(DEFAULT_CONFIG)
    print(f"promoted={outcome['promoted']} decision={args.decision}")
    return 0 if outcome["promoted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

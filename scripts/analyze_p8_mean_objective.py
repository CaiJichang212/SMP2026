#!/usr/bin/env python3
"""Analyze the fresh, preregistered P8 mean-objective confirmation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.summarize_p8_search import summarize
from starnet.experiments.p8_seeds import FAMILIES, NEW_FAMILIES


def stressed_gain(values):
    """Exact minimum over the declared bounded family-weight simplex."""
    if not values:
        raise ValueError("empty family values")
    count = len(values)
    minimum, maximum = .5 / count, 2.0 / count
    result = minimum * sum(values)
    remaining = 1.0 - minimum * count
    for value in sorted(values):
        extra = min(remaining, maximum - minimum)
        result += extra * value
        remaining -= extra
        if remaining <= 1e-12:
            break
    return result


def paired_summary(by_family, *, samples=10000):
    if not by_family or any(not values for values in by_family.values()):
        raise ValueError("empty family cohort")
    means = [statistics.fmean(values) for _, values in sorted(by_family.items())]
    rng = random.Random(20260913)
    averages, stresses = [], []
    for _ in range(samples):
        sampled = [statistics.fmean(rng.choices(values, k=len(values)))
                   for _, values in sorted(by_family.items())]
        averages.append(statistics.fmean(sampled))
        stresses.append(stressed_gain(sampled))
    averages.sort()
    stresses.sort()
    lower, upper = int(.025 * samples), int(.975 * samples)
    return {"mean_gain": statistics.fmean(means), "composition_stressed_gain": stressed_gain(means),
            "stratified_bootstrap_95_interval": [averages[lower], averages[upper]],
            "composition_stress_bootstrap_95_interval": [stresses[lower], stresses[upper]],
            "leave_one_family_out_min_mean": min((sum(means) - value) / (len(means) - 1) for value in means) if len(means) > 1 else None,
            "mean_score_statistical_gate_passed": stresses[lower] > 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standard-reports", nargs="+", type=Path, required=True)
    parser.add_argument("--shift-reports", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    variants = ("conservative", "audited")
    standard = summarize(args.standard_reports, families=FAMILIES, repetitions=tuple(range(701, 706)), strata=("standard",), variants=variants)
    shifts = summarize(args.shift_reports, families=NEW_FAMILIES, repetitions=(701, 702, 703), strata=("low", "high", "persona_correlated"), variants=variants)
    expected_hash = "56709076b9c89d7934899f046c20198f569575b165871adfc9055e49269500b0"
    for report in (standard, shifts):
        if not report["reported_policy_hashes"] or any(value != expected_hash for value in report["reported_policy_hashes"].values()):
            raise ValueError("policy hash differs from frozen mean-objective policy")
    rows = [row for path in args.standard_reports for row in json.loads(path.read_text())["rows"]]
    result = {}
    for variant in variants:
        selected = [row for row in rows if row["variant"] == variant]
        families = {family: [row["delta"] for row in selected if row["family"] == family] for family in FAMILIES}
        stats = paired_summary(families)
        shift_means = {stratum: arms[variant]["mean_delta"] for stratum, arms in shifts["strata"].items()}
        stats.update({"shift_mean_gains": shift_means,
                      "legacy_each_family_nonnegative": all(statistics.fmean(values) >= -1e-8 for values in families.values()),
                      "negative_cases": sum(row["delta"] < -1e-8 for row in selected),
                      "minimum_case_gain": min(row["delta"] for row in selected),
                      "family_mean_gains": {family: statistics.fmean(values) for family, values in families.items()}})
        stats["mean_score_gate_passed"] = stats["mean_score_statistical_gate_passed"] and min(shift_means.values()) >= -1e-8
        result[variant] = stats
    eligible = [variant for variant in variants if result[variant]["mean_score_gate_passed"]]
    selection = max(eligible, key=lambda variant: result[variant]["mean_gain"]) if eligible else None
    report = {"variants": result, "selected_variant": selection,
              "standard_audit": standard, "shift_audit": shifts,
              "protocol_sha256": hashlib.sha256((ROOT / "experiments/manifests/p8-mean-objective-confirmation-20260913.json").read_bytes()).hexdigest(),
              "production_enabled": False, "platform_score": None,
              "limitations": "Local declared-family mean and explicit bounded-weight sensitivity; no universal guarantee or official hidden-seed score."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"variants": result, "selected_variant": selection}), flush=True)


if __name__ == "__main__":
    main()

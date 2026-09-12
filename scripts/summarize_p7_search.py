#!/usr/bin/env python3
"""Audit complete paired P7 cohorts before reporting family-level gains."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import bootstrap_ci
from scripts.run_robust_search import BLOCKS


def summarize(paths: list[Path], repetitions: list[int]) -> dict:
    rows = []
    sources = []
    for path in paths:
        raw = path.read_bytes()
        report = json.loads(raw)
        config = report["config"]
        if config.get("nodes", config.get("node_count")) != 50:
            raise ValueError("P7 primary cohort must contain only 50-node runs")
        rows.extend(report["rows"])
        sources.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
    expected = {(family, repetition) for families, _ in BLOCKS.values()
                for family in families for repetition in repetitions}
    variants = sorted({row["variant"] for row in rows})
    if not variants:
        raise ValueError("empty cohort")
    summary = {}
    for variant in variants:
        selected = [row for row in rows if row["variant"] == variant]
        keys = [(row["family"], row["repetition"]) for row in selected]
        if len(keys) != len(set(keys)) or set(keys) != expected:
            raise ValueError(f"incomplete or duplicate cohort: {variant}")
        for row in selected:
            for arm in ("baseline", "candidate"):
                result = row[arm]
                if not math.isfinite(result["score"]) or result["failures"]:
                    raise ValueError("invalid score or failed action")
                spent = sum(result["actions"][kind] * cost for kind, cost in
                            (("scan", .5), ("comm", 2), ("cut", 3), ("shield", 5)))
                steps = sum(result["actions"].values())
                if (result["remaining_budget"] < 0 or steps > 117
                        or not math.isclose(spent + result["remaining_budget"], 100.0)):
                    raise ValueError("resource audit failed")
            if not math.isclose(row["delta"], row["candidate"]["score"] - row["baseline"]["score"], abs_tol=1e-8):
                raise ValueError("paired delta mismatch")
        means = {family: statistics.mean(row["delta"] for row in selected if row["family"] == family)
                 for family, _ in sorted(expected)}
        deltas = [row["delta"] for row in selected]
        interval = bootstrap_ci(list(means.values()))
        summary[variant] = {
            "cases": len(selected),
            "baseline_mean": statistics.mean(row["baseline"]["score"] for row in selected),
            "candidate_mean": statistics.mean(row["candidate"]["score"] for row in selected),
            "mean_delta": statistics.mean(deltas), "family_mean_delta": means,
            "family_bootstrap_95_interval": interval,
            "win_tie_loss": [sum(x > 1e-8 for x in deltas), sum(abs(x) <= 1e-8 for x in deltas), sum(x < -1e-8 for x in deltas)],
            "minimum_delta": min(deltas), "maximum_delta": max(deltas),
            "all_family_means_nonnegative": min(means.values()) >= -1e-8,
            "statistical_gate_passed": min(means.values()) >= -1e-8 and interval[0] > 0,
            "resource_audit_passed": True,
        }
    return {"repetitions": repetitions, "sources": sources, "summary": summary,
            "platform_score": None, "production_promotion_allowed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--repetitions", type=int, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.reports, args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

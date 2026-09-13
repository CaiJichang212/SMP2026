#!/usr/bin/env python3
"""Audit and summarize paired P8 search reports without mixing r strata."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any, Iterable

from starnet.experiments.p8_seeds import FAMILIES, R_STRATA


def _declared(config: dict[str, Any], key: str) -> tuple[Any, ...]:
    value = config.get(key)
    if not isinstance(value, list) or not value or len(value) != len(set(value)):
        raise ValueError(f"config.{key} must be a non-empty unique list")
    return tuple(value)


def _validate_arm(arm: object, *, label: str) -> None:
    if not isinstance(arm, dict):
        raise ValueError(f"{label} must be an object")
    score = arm.get("score")
    remaining = arm.get("remaining_budget")
    failures = arm.get("failures")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in (score, remaining)):
        raise ValueError(f"{label} has nonfinite score or budget")
    if failures != 0 or remaining < 0:
        raise ValueError(f"{label} has failures or negative budget")
    actions = arm.get("actions")
    if not isinstance(actions, dict):
        raise ValueError(f"{label}.actions must be an object")
    counts = []
    for kind in ("scan", "comm", "cut", "shield"):
        value = actions.get(kind)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label} has invalid {kind} count")
        counts.append(value)
    if actions["scan"] != 50:
        raise ValueError(f"{label} must scan exactly 50 nodes")
    steps = arm.get("steps", sum(counts))
    if isinstance(steps, bool) or not isinstance(steps, int) or steps != sum(counts) or steps > 117:
        raise ValueError(f"{label} has invalid step accounting")
    spent = 0.5 * actions["scan"] + 2 * actions["comm"] + 3 * actions["cut"] + 5 * actions["shield"]
    if not math.isclose(100.0 - spent, float(remaining), rel_tol=0.0, abs_tol=1e-8):
        raise ValueError(f"{label} has invalid budget accounting")


def _bootstrap(values: list[float], identity: str, samples: int = 10_000) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    estimates = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples))
    return [estimates[int(samples * 0.025)], estimates[int(samples * 0.975)]]


def _policy_identity(report: dict[str, Any]) -> object | None:
    config = report.get("config") if isinstance(report.get("config"), dict) else {}
    for key in ("policy_hash", "policy_sha256", "policy_hashes"):
        if key in report:
            return report[key]
        if key in config:
            return config[key]
    return None


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def summarize(
    paths: Iterable[Path], *, families: tuple[str, ...], repetitions: tuple[int, ...],
    strata: tuple[str, ...], variants: tuple[str, ...],
) -> dict[str, Any]:
    expected = {
        (family, repetition, stratum, variant)
        for family in families for repetition in repetitions
        for stratum in strata for variant in variants
    }
    rows_by_key: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    source_hashes = {}
    policy_hashes = {}
    missing_policy_hashes = []
    for raw_path in paths:
        path = Path(raw_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        config = data.get("config")
        rows = data.get("rows")
        if not isinstance(config, dict) or not isinstance(rows, list):
            raise ValueError(f"{path} must contain config and rows")
        node_count = config.get("nodes", config.get("node_count"))
        if node_count != 50:
            raise ValueError(f"{path} must declare 50 nodes")
        declared_families = _declared(config, "families")
        declared_repetitions = tuple(_declared(config, "repetitions"))
        declared_strata = _declared(config, "strata")
        declared_variants = _declared(config, "variants")
        declared_cases = {
            (family, repetition, stratum, variant)
            for family in declared_families for repetition in declared_repetitions
            for stratum in declared_strata for variant in declared_variants
        }
        actual_cases = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{path} contains a non-object row")
            key = tuple(row.get(name) for name in ("family", "repetition", "r_stratum", "variant"))
            if key in rows_by_key or key in actual_cases:
                raise ValueError(f"duplicate P8 case: {key}")
            actual_cases.append(key)
            seed_hash = row.get("seed_sha256")
            if not isinstance(seed_hash, str) or len(seed_hash) != 64:
                raise ValueError(f"invalid seed hash for {key}")
            baseline, candidate = row.get("baseline"), row.get("candidate")
            _validate_arm(baseline, label=f"{key}.baseline")
            _validate_arm(candidate, label=f"{key}.candidate")
            delta = row.get("delta")
            if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not math.isfinite(delta):
                raise ValueError(f"nonfinite delta for {key}")
            if not math.isclose(delta, candidate["score"] - baseline["score"], rel_tol=0.0, abs_tol=1e-8):
                raise ValueError(f"delta does not match scores for {key}")
            rows_by_key[key] = row
        if set(actual_cases) != declared_cases:
            raise ValueError(f"{path} does not match its declared Cartesian cases")
        source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        identity = _policy_identity(data)
        if identity is not None:
            policy_hashes[str(path)] = identity
        else:
            missing_policy_hashes.append(str(path))
    if policy_hashes and missing_policy_hashes:
        raise ValueError("policy hash is present for only some source reports")
    if len({_canonical(value) for value in policy_hashes.values()}) > 1:
        raise ValueError("source reports use inconsistent policy hashes")
    if set(rows_by_key) != expected:
        missing = len(expected - set(rows_by_key))
        unexpected = len(set(rows_by_key) - expected)
        raise ValueError(f"combined reports do not match requested Cartesian cases: missing={missing} unexpected={unexpected}")

    # Every arm for one seed must use exactly the same seed and baseline score.
    seed_groups: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for (family, repetition, stratum, _variant), row in rows_by_key.items():
        seed_groups[(family, repetition, stratum)].append(row)
    for key, rows in seed_groups.items():
        if len({row["seed_sha256"] for row in rows}) != 1:
            raise ValueError(f"cross-arm seed hash mismatch for {key}")
        if len({float(row["baseline"]["score"]) for row in rows}) != 1:
            raise ValueError(f"cross-arm baseline score mismatch for {key}")
        baseline_state = {
            _canonical({name: row["baseline"].get(name)
                        for name in ("actions", "remaining_budget", "failures")})
            for row in rows
        }
        if len(baseline_state) != 1:
            raise ValueError(f"cross-arm baseline action mismatch for {key}")

    by_stratum = {}
    for stratum in strata:
        variant_summary = {}
        for variant in variants:
            selected = [row for key, row in rows_by_key.items() if key[2] == stratum and key[3] == variant]
            family_stats = {}
            for family in families:
                family_rows = [row for row in selected if row["family"] == family]
                family_stats[family] = {
                    "cases": len(family_rows),
                    "baseline_mean": statistics.fmean(row["baseline"]["score"] for row in family_rows),
                    "candidate_mean": statistics.fmean(row["candidate"]["score"] for row in family_rows),
                    "mean_delta": statistics.fmean(row["delta"] for row in family_rows),
                }
            family_means = [value["mean_delta"] for value in family_stats.values()]
            deltas = [row["delta"] for row in selected]
            baseline_mean = statistics.fmean(row["baseline"]["score"] for row in selected)
            candidate_mean = statistics.fmean(row["candidate"]["score"] for row in selected)
            ci = _bootstrap(family_means, f"{stratum}:{variant}")
            relative_gain = (
                100.0 * (candidate_mean - baseline_mean) / baseline_mean
                if not math.isclose(baseline_mean, 0.0, abs_tol=1e-15)
                else None
            )
            variant_summary[variant] = {
                "cases": len(selected),
                "baseline_mean": baseline_mean,
                "candidate_mean": candidate_mean,
                "mean_delta": statistics.fmean(deltas),
                "relative_gain_percent": relative_gain,
                "win_tie_loss": [sum(value > 1e-8 for value in deltas),
                                 sum(abs(value) <= 1e-8 for value in deltas),
                                 sum(value < -1e-8 for value in deltas)],
                "min_delta": min(deltas),
                "max_delta": max(deltas),
                "family_bootstrap_95_ci": ci,
                "all_family_means_nonnegative": min(family_means) >= -1e-8,
                "local_gate_passed": min(family_means) >= -1e-8 and ci[0] > 0,
                "families": family_stats,
            }
        by_stratum[stratum] = variant_summary
    return {
        "schema_version": 1,
        "source_sha256": source_hashes,
        "reported_policy_hashes": policy_hashes,
        "config": {"nodes": 50, "families": list(families), "repetitions": list(repetitions),
                   "strata": list(strata), "variants": list(variants)},
        "strata": by_stratum,
        "cross_stratum_aggregate": None,
        "production_enabled": False,
        "platform_score": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--families", nargs="+", choices=FAMILIES, required=True)
    parser.add_argument("--repetitions", nargs="+", type=int, required=True)
    parser.add_argument("--strata", nargs="+", choices=R_STRATA, required=True)
    parser.add_argument("--variants", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name, values in (("families", args.families), ("repetitions", args.repetitions),
                         ("strata", args.strata), ("variants", args.variants)):
        if len(values) != len(set(values)):
            parser.error(f"--{name} values must be unique")
    result = summarize(args.reports, families=tuple(args.families), repetitions=tuple(args.repetitions),
                       strata=tuple(args.strata), variants=tuple(args.variants))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["strata"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

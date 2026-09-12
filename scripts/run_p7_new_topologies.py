#!/usr/bin/env python3
"""Run frozen P7 candidates on the five new topology families."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import run_variant
from scripts.run_robust_search import run_robust
from scripts.run_rollout_search import run_search as run_rollout
from starnet.experiments.p7_seeds import (
    CONFIRMATION_REPETITIONS,
    DEVELOPMENT_REPETITIONS,
    FAMILIES,
    R_STRATA,
    seed_payload,
)


VARIANTS = ("strict_anchor", "bounded_anchor", "mean")


def seed_hash(seed: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest()


def run_matrix(
    *, repetitions: tuple[int, ...], strata: tuple[str, ...],
    variants: tuple[str, ...], families: tuple[str, ...] = FAMILIES,
    on_row: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    rows = []
    for family in families:
        for repetition in repetitions:
            for r_stratum in strata:
                seed = seed_payload(family, repetition, r_stratum)
                baseline = run_variant(seed, "public_greedy")
                robust_cache: dict[tuple, object] = {}
                for variant in variants:
                    candidate = (
                        run_rollout(seed, scenario_count=1)
                        if variant == "mean"
                        else run_robust(seed, mode=variant, plan_cache=robust_cache)
                    )
                    row = {
                        "family": family,
                        "repetition": repetition,
                        "variant": variant,
                        "baseline": baseline,
                        "candidate": candidate,
                        "delta": candidate["score"] - baseline["score"],
                        "r_stratum": r_stratum,
                        "seed_sha256": seed_hash(seed),
                    }
                    rows.append(row)
                    if on_row is not None:
                        on_row(row)

    def summarize(selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
        result = {}
        for variant in variants:
            arm_rows = [row for row in selected_rows if row["variant"] == variant]
            family_means = {
                family: statistics.fmean(row["delta"] for row in arm_rows if row["family"] == family)
                for family in families
            }
            deltas = [row["delta"] for row in arm_rows]
            result[variant] = {
                "cases": len(arm_rows),
                "mean_delta": statistics.fmean(deltas),
                "family_mean_delta": family_means,
                "all_family_means_nonnegative": all(value >= -1e-8 for value in family_means.values()),
                "win_tie_loss": [
                    sum(value > 1e-8 for value in deltas),
                    sum(abs(value) <= 1e-8 for value in deltas),
                    sum(value < -1e-8 for value in deltas),
                ],
                "failures": sum(row["candidate"]["failures"] for row in arm_rows),
                "budget_and_steps_valid": all(
                    row["candidate"]["remaining_budget"] >= 0
                    and row["candidate"]["steps"] <= 117
                    for row in arm_rows
                ),
            }
        return result

    stratum_summary = {
        stratum: summarize([row for row in rows if row["r_stratum"] == stratum])
        for stratum in strata
    }
    return {
        "config": {
            "block": "new5",
            "node_count": 50,
            "families": list(families),
            "repetitions": list(repetitions),
            "strata": list(strata),
            "variants": list(variants),
            "cohort": (
                "development" if set(repetitions).issubset(DEVELOPMENT_REPETITIONS)
                else "confirmation"
            ),
            "shared_robust_cache_per_seed": True,
        },
        "rows": rows,
        "summary": stratum_summary[strata[0]] if len(strata) == 1 else {},
        "stratum_summary": stratum_summary,
        "platform_score": None,
        "production_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--repetitions", nargs="+", type=int, default=list(DEVELOPMENT_REPETITIONS))
    parser.add_argument("--strata", nargs="+", choices=tuple(R_STRATA), default=["standard"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repetitions = tuple(dict.fromkeys(args.repetitions))
    strata = tuple(dict.fromkeys(args.strata))
    variants = tuple(dict.fromkeys(args.variants))
    development = set(repetitions).issubset(DEVELOPMENT_REPETITIONS)
    confirmation = set(repetitions).issubset(CONFIRMATION_REPETITIONS)
    if not repetitions or not (development or confirmation):
        parser.error("repetitions must belong wholly to development 301-303 or confirmation 401-405")
    report = run_matrix(
        repetitions=repetitions, strata=strata, variants=variants,
        on_row=lambda row: print(json.dumps(row, ensure_ascii=False), flush=True),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["stratum_summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Replay guarded P10 on the consumed 48-case cohort against frozen controls."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_p10_combined_confirmation import (
    ARCHIVES, digest, first_divergence, json_digest, run_candidate, source_snapshot,
    write_json,
)
from starnet.experiments.p10_confirmation_seeds import (
    CONFIRMATION_REPETITIONS, FAMILIES, STRATA, seed_payload,
)


PROTOCOL = ROOT / "experiments/manifests/p10-guarded-combined-20260914.json"
REFERENCE_RAW = ROOT / "experiments/raw/p10-combined-confirmation-20260914/full.json"


def run_case(job):
    family, repetition, stratum, expected_snapshot = job
    if source_snapshot() != expected_snapshot:
        raise RuntimeError("guarded source changed before case execution")
    seed = seed_payload(family, repetition, stratum, allow_confirmation=True)
    candidate = run_candidate(seed, "guarded_combined")
    if source_snapshot() != expected_snapshot:
        raise RuntimeError("guarded source changed during case execution")
    return family, repetition, stratum, json_digest(seed), candidate


def metric(rows, comparison):
    values = [row["paired_deltas"][comparison] for row in rows]
    return {
        "cases": len(values), "mean": statistics.fmean(values),
        "minimum": min(values), "maximum": max(values),
        "win_tie_loss": [sum(value > 1e-8 for value in values),
                         sum(abs(value) <= 1e-8 for value in values),
                         sum(value < -1e-8 for value in values)],
        "losses": [{"family": row["family"], "repetition": row["repetition"],
                    "stratum": row["stratum"], "delta": value}
                   for row, value in zip(rows, values) if value < -1e-8],
    }


def summarize(rows):
    comparisons = ("guarded_vs_p9", "guarded_vs_official_best")
    return {
        "overall": {name: metric(rows, name) for name in comparisons},
        "by_stratum": {stratum: {name: metric(
            [row for row in rows if row["stratum"] == stratum], name,
        ) for name in comparisons} for stratum in STRATA},
        "by_family": {family: {name: metric(
            [row for row in rows if row["family"] == family], name,
        ) for name in comparisons} for family in FAMILIES},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(REFERENCE_RAW.read_text())
    if reference.get("complete") is not True or len(reference.get("rows", [])) != 48:
        raise ValueError("frozen P10 reference raw is incomplete")
    reference_rows = {
        (row["family"], row["repetition"], row["stratum"]): row
        for row in reference["rows"]
    }
    snapshot = source_snapshot()
    config = {
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "reference_raw_sha256": digest(REFERENCE_RAW),
        "reference_runner_sha256": reference["config"]["runner_sha256"],
        "generator_sha256": digest(ROOT / "src/starnet/experiments/p10_confirmation_seeds.py"),
        "source_snapshot": snapshot,
        "variant": "guarded_combined", "workers": args.workers,
        "families": list(FAMILIES), "strata": list(STRATA),
        "repetitions": list(CONFIRMATION_REPETITIONS),
        "new_confirmation_opened": False,
    }
    progress = args.raw_output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("guarded progress identity mismatch")
        rows = list(saved.get("rows", []))
    completed = {(row["family"], row["repetition"], row["stratum"]) for row in rows}
    jobs = [(family, repetition, stratum, snapshot)
            for family in FAMILIES for repetition in CONFIRMATION_REPETITIONS for stratum in STRATA
            if (family, repetition, stratum) not in completed]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_case, job): job for job in jobs}
        for future in as_completed(futures):
            family, repetition, stratum, seed_sha256, candidate = future.result()
            reference_row = reference_rows[family, repetition, stratum]
            if reference_row["seed_sha256"] != seed_sha256:
                raise ValueError("guarded/reference seed mismatch")
            p9 = reference_row["arms"]["p9_archive"]
            official = reference_row["arms"]["official_best_archive"]
            row = {
                "family": family, "repetition": repetition, "stratum": stratum,
                "seed_sha256": seed_sha256,
                "arms": {"guarded_candidate": candidate,
                         "p9_archive": p9, "official_best_archive": official},
                "paired_deltas": {
                    "guarded_vs_p9": candidate["score"] - p9["score"],
                    "guarded_vs_official_best": candidate["score"] - official["score"],
                },
                "first_divergence": {
                    "guarded_vs_p9": first_divergence(candidate, p9),
                    "guarded_vs_official_best": first_divergence(candidate, official),
                },
            }
            rows.append(row)
            rows.sort(key=lambda item: (item["repetition"], FAMILIES.index(item["family"]),
                                        STRATA.index(item["stratum"])))
            write_json(progress, {"config": config, "rows": rows})
            print(json.dumps({"family": family, "repetition": repetition,
                              "stratum": stratum, "delta": row["paired_deltas"]["guarded_vs_p9"],
                              "completed": len(rows)}), flush=True)
    if len(rows) != 48:
        raise ValueError("guarded consumed cohort incomplete")
    raw = {"config": config, "complete": True, "rows": rows}
    write_json(args.raw_output, raw)
    summary = summarize(rows)
    stratum_pass = all(
        summary["by_stratum"][stratum]["guarded_vs_p9"]["mean"] >= -1e-8
        for stratum in STRATA
    )
    compact = {
        "config": config, "complete": True, "summary": summary,
        "development_gate_passed": (
            summary["overall"]["guarded_vs_p9"]["mean"] > 0.0 and stratum_pass
        ),
        "raw_log": {"path": str(args.raw_output.resolve().relative_to(ROOT)),
                    "sha256": digest(args.raw_output), "committed": False},
        "rows": [{
            "family": row["family"], "repetition": row["repetition"],
            "stratum": row["stratum"], "seed_sha256": row["seed_sha256"],
            "paired_deltas": row["paired_deltas"],
            "first_divergence": row["first_divergence"],
            "guarded": {key: row["arms"]["guarded_candidate"].get(key) for key in (
                "score", "remaining_budget", "host_calls", "action_attempts",
                "action_failures", "action_log_sha256", "llm_calls", "llm_accepted",
                "p8_planning_errors", "p10_planning_errors", "p10_searches",
                "p10_approved_plans", "p10_prefix_completed", "p10_prefix_failures",
                "p10_response_switches", "p10_response_activation",
                "p10_response_disabled", "p10_initial_degrees_configured",
                "p10_initial_degree_count", "p10_initial_degree_config_errors",
            )},
        } for row in rows],
        "new_confirmation_opened": False, "production_enabled": False,
    }
    write_json(args.output, compact)
    print(json.dumps({"development_gate_passed": compact["development_gate_passed"],
                      "summary": summary}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

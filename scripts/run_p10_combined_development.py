#!/usr/bin/env python3
"""Complete the preregistered 18-case P10 four-arm development matrix."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_p10_runtime_arm_comparison import (
    ARMS, SOURCE_PATHS, digest, first_divergence, json_digest, run_arm, write_json,
)
from starnet.experiments.p9_distribution_seeds import seed_payload


PROTOCOL = ROOT / "experiments/manifests/p10-combined-validation-20260914.json"
FAMILIES = ("er_resampled", "ba_resampled", "ws_resampled", "sbm_resampled")
STRATA = ("centered_independent", "negative_persona_aligned", "positive_persona_inverse")


def run_case(family, stratum):
    seed = seed_payload(family, 901, stratum)
    arms = {arm: run_arm(seed, arm) for arm in ARMS}
    return {
        "case_id": f"p9:{family}:901:{stratum}",
        "group": stratum,
        "family": family,
        "repetition": 901,
        "seed_sha256": json_digest(seed),
        "arms": arms,
        "first_divergence": {
            arm: first_divergence(arms[arm]["action_sequence"], arms["p9"]["action_sequence"])
            for arm in ARMS if arm != "p9"
        },
    }


def metric(rows, arm):
    values = [row["arms"][arm]["score"] - row["arms"]["p9"]["score"] for row in rows]
    return {
        "cases": len(values), "mean": statistics.fmean(values),
        "minimum": min(values), "maximum": max(values),
        "win_tie_loss": [sum(value > 1e-8 for value in values),
                         sum(abs(value) <= 1e-8 for value in values),
                         sum(value < -1e-8 for value in values)],
        "losses": [
            {"case_id": row["case_id"], "delta": value}
            for row, value in zip(rows, values) if value < -1e-8
        ],
    }


def compact_arm(result):
    return {key: value for key, value in result.items() if key != "action_sequence"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-input", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    source_sha256 = {relative: digest(ROOT / relative) for relative in SOURCE_PATHS}
    legacy = json.loads(args.legacy_input.read_text())
    if (legacy.get("complete") is not True or len(legacy.get("rows", [])) != 6
            or legacy.get("config", {}).get("source_sha256") != source_sha256
            or legacy.get("config", {}).get("arms") != list(ARMS)):
        raise ValueError("legacy P10 block is incomplete or has stale source identity")
    legacy_rows = [{
        **row,
        "case_id": f"legacy:{row['family']}:1",
        "group": "legacy_independent",
    } for row in legacy["rows"]]
    config = {
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "source_sha256": source_sha256,
        "legacy_input_sha256": digest(args.legacy_input),
        "arms": list(ARMS), "workers": args.workers,
        "case_count": 18,
    }
    progress = args.raw_output.with_suffix(".progress.json")
    rows = list(legacy_rows)
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("combined development progress identity mismatch")
        rows = list(saved.get("rows", []))
    completed = {row["case_id"] for row in rows}
    jobs = [(family, stratum) for family in FAMILIES for stratum in STRATA
            if f"p9:{family}:901:{stratum}" not in completed]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_case, *job): job for job in jobs}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            rows.sort(key=lambda item: item["case_id"])
            write_json(progress, {"config": config, "rows": rows})
            print(json.dumps({
                "case_id": row["case_id"], "completed": len(rows),
                "scores": {arm: row["arms"][arm]["score"] for arm in ARMS},
            }), flush=True)
    if len(rows) != 18 or len({row["case_id"] for row in rows}) != 18:
        raise ValueError("combined development cohort is incomplete")
    raw = {"config": config, "complete": True, "rows": rows}
    write_json(args.raw_output, raw)
    groups = ("legacy_independent", *STRATA)
    compact = {
        "config": config, "complete": True,
        "raw_log": {"path": str(args.raw_output.resolve().relative_to(ROOT)),
                    "sha256": digest(args.raw_output), "committed": False},
        "overall": {arm: metric(rows, arm) for arm in ARMS if arm != "p9"},
        "by_group": {
            group: {arm: metric([row for row in rows if row["group"] == group], arm)
                    for arm in ARMS if arm != "p9"}
            for group in groups
        },
        "rows": [{
            "case_id": row["case_id"], "group": row["group"],
            "family": row["family"], "repetition": row["repetition"],
            "seed_sha256": row["seed_sha256"],
            "first_divergence": row["first_divergence"],
            "arms": {arm: compact_arm(result) for arm, result in row["arms"].items()},
        } for row in rows],
        "confirmation_opened": False, "production_enabled": False,
    }
    write_json(args.output, compact)
    print(json.dumps({"overall": compact["overall"], "by_group": compact["by_group"]}),
                     flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

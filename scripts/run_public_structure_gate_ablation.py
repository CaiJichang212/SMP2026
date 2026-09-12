#!/usr/bin/env python3
"""Paired screening of public-only structure risk gates.

This only changes the candidate screen used by the existing controller. The
settlement surrogate and hidden response factors remain inside the local
environment; no submission behavior is changed by this script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from run_local_policy_matrix import (
    HOLDOUT_FAMILIES,
    INDEPENDENT_FAMILIES,
    holdout_seed_payload,
    independent_seed_payload,
    run_variant,
)
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.policy import structural


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=("existing", "independent", "holdout"), required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    families, make_seed = {
        "existing": (SEED_SPECS, seed_payload),
        "independent": (INDEPENDENT_FAMILIES, independent_seed_payload),
        "holdout": (HOLDOUT_FAMILIES, holdout_seed_payload),
    }[args.block]
    original_gate = structural.public_structure_risk_allowed
    rows = []
    try:
        for family in families:
            for repetition in range(1, args.repetitions + 1):
                seed = make_seed(family, 50, repetition)
                for variant in ("current", "positive_gate_only", "all_positive_gain"):
                    if variant == "current":
                        structural.public_structure_risk_allowed = original_gate
                    elif variant == "positive_gate_only":
                        structural.public_structure_risk_allowed = (
                            lambda board, action, gain: gain > 0.0
                            and not structural.public_positive_graph_gate_closed(board)
                        )
                    else:
                        structural.public_structure_risk_allowed = (
                            lambda board, action, gain: gain > 0.0
                        )
                    started = time.monotonic()
                    result = run_variant(seed, "public_greedy")
                    rows.append({
                        "family": family,
                        "repetition": repetition,
                        "variant": variant,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        **result,
                    })
    finally:
        structural.public_structure_risk_allowed = original_gate
    by_key = {(row["family"], row["repetition"]): row for row in rows if row["variant"] == "current"}
    summary = {}
    for variant in ("positive_gate_only", "all_positive_gain"):
        selected = [row for row in rows if row["variant"] == variant]
        family_deltas = {
            family: sum(
                row["score"] - by_key[(family, row["repetition"])]["score"]
                for row in selected if row["family"] == family
            ) / args.repetitions
            for family in families
        }
        summary[variant] = {
            "mean_paired_delta": sum(family_deltas.values()) / len(family_deltas),
            "family_mean_deltas": family_deltas,
            "all_family_means_nonnegative": all(value >= 0.0 for value in family_deltas.values()),
            "failures": sum(row["failures"] for row in selected),
        }
    payload = {
        "block": args.block,
        "node_count": 50,
        "repetitions": args.repetitions,
        "comparison": "same generated seed and public-API controller; only structure risk screen differs",
        "rows": rows,
        "summary": summary,
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

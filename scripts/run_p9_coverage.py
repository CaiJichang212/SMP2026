#!/usr/bin/env python3
"""Paired development experiment, reusing the unchanged public episode runner."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_p8_search import run_p8, seed_hash
from starnet.experiments.p8_seeds import FAMILIES, seed_payload
from starnet.policy.p9_coverage_experiment import choose_coverage_action


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, nargs="+", default=[501])
    parser.add_argument("--families", nargs="+", choices=FAMILIES, default=list(FAMILIES))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not set(args.repetitions).issubset({501, 502, 503}):
        parser.error("Only consumed development data is permitted")
    config = {"families": args.families, "repetitions": args.repetitions,
              "policy_sha256": hashlib.sha256((ROOT / "src/starnet/policy/p9_coverage_experiment.py").read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256((ROOT / "experiments/manifests/p9-coverage-development-20260913.json").read_bytes()).hexdigest()}
    rows = []
    if args.output.exists():
        previous = json.loads(args.output.read_text())
        if previous["config"] != config:
            raise ValueError("output belongs to a different frozen experiment")
        rows = previous["rows"]
    done = {(row["family"], row["repetition"]) for row in rows}
    for family in args.families:
        for repetition in args.repetitions:
            if (family, repetition) in done:
                continue
            seed = seed_payload(family, repetition)
            baseline = run_p8(seed, "conservative")
            # Only replace the local runner's decision callback. Neither the
            # submitted framework nor the environment is patched or faked.
            with patch("scripts.run_p8_search.choose_p8_action", choose_coverage_action):
                candidate = run_p8(seed, "conservative")
            row = {"family": family, "repetition": repetition, "seed_sha256": seed_hash(seed),
                   "baseline": baseline, "candidate": candidate,
                   "delta": candidate["score"] - baseline["score"]}
            rows.append(row)
            deltas = [row["delta"] for row in rows]
            report = {"config": config, "rows": rows, "production_enabled": False,
                      "summary": {"cases": len(rows), "mean_delta": statistics.fmean(deltas),
                                  "min_delta": min(deltas),
                                  "wins_ties_losses": [sum(x > 1e-8 for x in deltas), sum(abs(x) <= 1e-8 for x in deltas), sum(x < -1e-8 for x in deltas)],
                                  "failures": sum(row["candidate"]["failures"] for row in rows)}}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"family": family, "repetition": repetition, "delta": row["delta"],
                              "seconds": candidate["seconds"]}), flush=True)


if __name__ == "__main__":
    main()

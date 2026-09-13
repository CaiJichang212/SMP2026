#!/usr/bin/env python3
"""Validate P8 public actions on the official custom-seed sandbox."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_p7_remote_probe import PairedEnvironment, run_baseline
from scripts.run_p8_search import run_p8, seed_hash
from starnet.experiments.p8_seeds import DEVELOPMENT_REPETITIONS, FAMILIES, seed_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=FAMILIES, required=True)
    parser.add_argument("--repetition", choices=DEVELOPMENT_REPETITIONS, type=int, default=501)
    parser.add_argument("--variant", choices=("expected", "conservative"), default="conservative")
    parser.add_argument("--server-url", default="http://8.222.218.162:5000")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seed = seed_payload(args.family, args.repetition)
    report = {
        "family": args.family, "repetition": args.repetition, "r_stratum": "standard",
        "seed_sha256": seed_hash(seed),
        "policy_sha256": hashlib.sha256((ROOT / "src/starnet/policy/p8_experiment.py").read_bytes()).hexdigest(),
        "evaluation": "official custom-seed sandbox; deterministic research arms, no LLM",
        "platform_score": None, "production_promotion_allowed": False, "rows": [],
    }
    for variant in ("baseline", args.variant):
        started = time.perf_counter()
        env = PairedEnvironment(seed, args.server_url, args.timeout)
        result = (run_baseline(seed, env) if variant == "baseline" else
                  run_p8(seed, variant, env_factory=lambda _: env))
        result.update({"variant": variant, "local_replay_score": env.local_score,
                       "settlement_residual": env.remote_score - env.local_score,
                       "maximum_response_error": env.response_error,
                       "seconds": time.perf_counter() - started})
        report["rows"].append(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "deviations"}), flush=True)
    report["paired_gain"] = report["rows"][1]["score"] - report["rows"][0]["score"]
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Small preregistered integer-plan development experiment."""
from __future__ import annotations
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_p8_search import run_p8, seed_hash
from starnet.experiments.p8_seeds import seed_payload
from starnet.experiments.seeds import SEED_SPECS
from starnet.policy.p8_experiment import P8Decision, choose_p8_action
from starnet.policy.p10_integer_plan_experiment import choose_integer_prefix


def run_integer(seed, strict):
    pending = deque()
    diagnostic = {}
    started = False

    def chooser(board, budget, observed, *, remaining_steps, salt, mode, evaluation_cache):
        nonlocal started, diagnostic
        if not started:
            actions, diagnostic = choose_integer_prefix(board, budget, observed,
                remaining_steps=remaining_steps, salt=salt, strict=strict)
            pending.extend(actions)
            started = True
        if pending:
            action = pending.popleft()
            return P8Decision(action, action, "integer_prefix", (action,), (), 0., 0., 0)
        return choose_p8_action(board, budget, observed, remaining_steps=remaining_steps,
                               salt=salt, mode=mode, evaluation_cache=evaluation_cache)

    with patch("scripts.run_p8_search.choose_p8_action", chooser):
        result = run_p8(seed, "conservative")
    result["integer_plan"] = diagnostic
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = ["src/starnet/policy/p10_integer_plan_experiment.py", "src/starnet/policy/p9_prefix_experiment.py", "src/starnet/policy/p8_experiment.py"]
    config = {"cohort": "legacy6/501/standard", "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}}
    rows = []
    for family in SEED_SPECS:
        seed = seed_payload(family, 501)
        baseline = run_p8(seed, "conservative")
        for mode in ("strict", "mean_audited"):
            candidate = run_integer(seed, mode == "strict")
            row = {"family": family, "mode": mode, "seed_sha256": seed_hash(seed),
                   "baseline": baseline, "candidate": candidate, "delta": candidate["score"] - baseline["score"]}
            rows.append(row)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"config": config, "rows": rows}, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"family": family, "mode": mode, "delta": row["delta"], "seconds": candidate["seconds"], "plan": candidate["integer_plan"]}), flush=True)


if __name__ == "__main__":
    main()

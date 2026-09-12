#!/usr/bin/env python3
"""Audit and summarize frozen paired budget-search experiments."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

try:
    from scripts.run_local_policy_matrix import HOLDOUT_FAMILIES, INDEPENDENT_FAMILIES
except ModuleNotFoundError:
    from run_local_policy_matrix import HOLDOUT_FAMILIES, INDEPENDENT_FAMILIES
from starnet.experiments.seeds import SEED_SPECS


def summarize(paths, *, gate="off"):
    if gate not in {"off", "negative_mass"}:
        raise ValueError("unknown confirmation gate")
    start = 101 if gate == "off" else 201
    repetitions = range(start, start + 5)
    groups = defaultdict(list)
    seen = set()
    inputs = {}
    expected_families = set(SEED_SPECS) | set(INDEPENDENT_FAMILIES) | set(HOLDOUT_FAMILIES)
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        config = data["config"]
        if (config["depth"], config["width"], config.get("observation_slots", 0)) != (2, 4, 0):
            raise ValueError("confirmation summary requires frozen depth=2 width=4 observation_slots=0")
        if config.get("gate", "off") != gate:
            raise ValueError("report gate differs from frozen confirmation gate")
        if config["start"] != start or config["repetitions"] != 5:
            raise ValueError(f"confirmation summary requires repetitions {start} through {start + 4}")
        inputs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        for row in data["rows"]:
            key = (config["nodes"], row["family"], row["repetition"])
            if key in seen:
                raise ValueError(f"duplicate paired case: {key}")
            seen.add(key)
            groups[config["nodes"]].append(row)
    result = {"inputs_sha256": inputs, "strata": {}, "production_enabled": False,
              "platform_score": None, "llm_quality_evaluated": False, "gate": gate}
    for node_count, rows in sorted(groups.items()):
        expected = {(node_count, family, repetition) for family in expected_families for repetition in repetitions}
        actual = {key for key in seen if key[0] == node_count}
        if actual != expected:
            raise ValueError(f"incomplete or unexpected {node_count}-node matrix")
        family_rows = defaultdict(list)
        for row in rows:
            family_rows[row["family"]].append(row)
            if not all(math.isfinite(value) for value in (row["delta"], row["candidate"]["score"], row["baseline"]["score"])):
                raise ValueError("nonfinite score or delta")
            if abs(row["delta"] - (row["candidate"]["score"] - row["baseline"]["score"])) > 1e-8:
                raise ValueError("paired delta does not match scores")
        families = {family: {"baseline": statistics.mean(row["baseline"]["score"] for row in values),
                             "candidate": statistics.mean(row["candidate"]["score"] for row in values),
                             "delta": statistics.mean(row["delta"] for row in values)}
                    for family, values in sorted(family_rows.items())}
        deltas = [row["delta"] for row in rows]
        family_deltas = [values["delta"] for values in families.values()]
        rng = random.Random(20260912)
        bootstrap = sorted(statistics.mean(rng.choices(family_deltas, k=len(family_deltas))) for _ in range(10000))
        ci = [bootstrap[249], bootstrap[9749]]
        failures = sum(row["candidate"]["failures"] + row["baseline"]["failures"] for row in rows)
        budget = 100 if node_count == 50 else 200
        step_limit = 117 if node_count == 50 else 247
        valid = True
        for row in rows:
            candidate = row["candidate"]
            actions = candidate["actions"]
            spent = 0.5 * actions["scan"] + 2 * actions["comm"] + 3 * actions["cut"] + 5 * actions["shield"]
            valid = valid and abs(budget - spent - candidate["remaining_budget"]) < 1e-8
            valid = valid and candidate["remaining_budget"] >= 0 and candidate["steps"] <= step_limit
            valid = valid and sum(actions.values()) == candidate["steps"] and actions["scan"] == node_count
        baseline_mean = statistics.mean(row["baseline"]["score"] for row in rows)
        candidate_mean = statistics.mean(row["candidate"]["score"] for row in rows)
        result["strata"][str(node_count)] = {
            "pairs": len(rows), "baseline_mean": baseline_mean, "candidate_mean": candidate_mean,
            "mean_delta": statistics.mean(deltas), "relative_gain_percent": 100 * (candidate_mean - baseline_mean) / baseline_mean,
            "win_tie_loss": [sum(delta > 1e-8 for delta in deltas), sum(abs(delta) <= 1e-8 for delta in deltas), sum(delta < -1e-8 for delta in deltas)],
            "min_delta": min(deltas), "max_delta": max(deltas), "family_bootstrap_95_ci": ci,
            "failures": failures, "budget_and_steps_valid": valid, "local_mean_above_900": candidate_mean > 900,
            "local_gate_passed": failures == 0 and valid and min(family_deltas) >= -1e-8 and ci[0] > 0,
            "families": families,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gate", choices=("off", "negative_mass"), default="off")
    args = parser.parse_args()
    result = summarize(args.inputs, gate=args.gate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

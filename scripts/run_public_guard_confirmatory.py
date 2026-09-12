#!/usr/bin/env python3
"""Run a frozen unseen-seed confirmation within known holdout families."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from run_local_policy_matrix import (
    HOLDOUT_FAMILIES,
    INDEPENDENT_FAMILIES,
    holdout_seed_payload,
    independent_seed_payload,
)
from run_public_comm_shield_guard import run_guarded
from run_public_joint_structure_screen import _run_public_greedy_with_audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=("independent", "holdout"), default="holdout")
    parser.add_argument("--node-count", type=int, default=50)
    parser.add_argument("--first-repetition", type=int, default=11)
    parser.add_argument("--last-repetition", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.node_count <= 0
        or args.first_repetition <= 0
        or args.last_repetition < args.first_repetition
    ):
        raise SystemExit("invalid repetition range")

    families = INDEPENDENT_FAMILIES if args.block == "independent" else HOLDOUT_FAMILIES
    make_seed = independent_seed_payload if args.block == "independent" else holdout_seed_payload
    pairs: list[dict[str, Any]] = []
    for family in families:
        for repetition in range(args.first_repetition, args.last_repetition + 1):
            seed = make_seed(family, args.node_count, repetition)
            baseline = _run_public_greedy_with_audit(seed)
            guard_off = run_guarded(seed, guard_enabled=False)
            equivalent = math.isclose(
                guard_off["score"], baseline["score"], rel_tol=0.0, abs_tol=1e-8,
            )
            if not equivalent:
                raise RuntimeError(f"guard-off mismatch for {family} r{repetition}")
            guarded = run_guarded(seed, guard_enabled=True)
            pairs.append({
                "family": family,
                "repetition": repetition,
                "public_greedy": baseline,
                "guard_disabled": guard_off,
                "guard_disabled_equivalent": equivalent,
                "comm_shield_guard": guarded,
                "delta": guarded["score"] - baseline["score"],
            })

    payload = {
        "schema_version": 1,
        "block": f"{args.block}-confirmatory",
        "families": list(families),
        "node_count": args.node_count,
        "repetition_range": [args.first_repetition, args.last_repetition],
        "pairs": pairs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

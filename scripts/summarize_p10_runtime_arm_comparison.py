#!/usr/bin/env python3
"""Create the compact P10 runtime audit from one complete ignored raw log."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_p10_runtime_arm_comparison import (
    ARMS, PROTOCOL, RESPONSE_REPORT, digest, metric, write_json,
)
from starnet.experiments.seeds import SEED_SPECS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.raw_input.read_text())
    rows = raw.get("rows", [])
    config = raw.get("config", {})
    if (raw.get("complete") is not True or len(rows) != 6
            or config.get("protocol_sha256") != digest(PROTOCOL)
            or config.get("response_report_sha256") != digest(RESPONSE_REPORT)
            or config.get("arms") != list(ARMS)
            or {row.get("family") for row in rows} != set(SEED_SPECS)):
        raise ValueError("raw P10 runtime cohort is incomplete or has stale identity")
    for row in rows:
        if set(row.get("arms", {})) != set(ARMS):
            raise ValueError("runtime row has incomplete arms")
        for result in row["arms"].values():
            if (result.get("action_failures") or result.get("p8_planning_errors")
                    or result.get("p10_planning_errors") or result.get("remaining_budget", -1) < 0
                    or result.get("action_attempts", 999) > 117):
                raise ValueError("runtime arm failed resource audit")
    response = json.loads(RESPONSE_REPORT.read_text())
    legacy_key = "gated_vs_fixed:gated__unrestricted:fixed__unrestricted"
    legacy = response["by_stratum"]["legacy_independent"][legacy_key]
    compact = {
        "config": config, "complete": True,
        "raw_log": {"path": str(args.raw_input.resolve().relative_to(ROOT)),
                    "sha256": digest(args.raw_input), "committed": False},
        "existing_response_evidence": {
            "cases": 18, "report_sha256": digest(RESPONSE_REPORT),
            "legacy_gated_vs_fixed": legacy,
        },
        "metrics_vs_p9": {arm: metric(rows, arm) for arm in ARMS if arm != "p9"},
        "rows": [{
            "family": row["family"], "repetition": 1,
            "seed_sha256": row["seed_sha256"],
            "first_divergence": row["first_divergence"],
            "arms": {arm: {key: value for key, value in result.items()
                           if key != "action_sequence"}
                     for arm, result in row["arms"].items()},
        } for row in rows],
        "confirmation_opened": False, "production_enabled": False,
    }
    write_json(args.output, compact)
    print(json.dumps(compact["metrics_vs_p9"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

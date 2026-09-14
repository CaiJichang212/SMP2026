#!/usr/bin/env python3
"""Compact the full P10 action/candidate log into reviewable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
FIXED = "fixed__full_gate"
PERSONA = "persona__full_gate"
POOLED = "pooled__full_gate"
NARROW = "fixed__full_gate_plus_negative_negative_cut"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stats(values):
    return {
        "cases": len(values),
        "mean": statistics.fmean(values),
        "minimum": min(values),
        "maximum": max(values),
        "win_tie_loss": [
            sum(value > 1e-8 for value in values),
            sum(abs(value) <= 1e-8 for value in values),
            sum(value < -1e-8 for value in values),
        ],
    }


def effect(rows, left, right):
    return stats([row["arms"][left]["score"] - row["arms"][right]["score"] for row in rows])


def candidate_set_change_count(rows, left, right):
    cases = decisions = 0
    by_kind = dict.fromkeys(("comm", "cut", "shield"), 0)
    for row in rows:
        changed_case = False
        for first, second in zip(row["arms"][left]["decisions"], row["arms"][right]["decisions"]):
            changed_decision = False
            for kind in by_kind:
                if set(first["candidate_ids_by_kind"][kind]) != set(second["candidate_ids_by_kind"][kind]):
                    by_kind[kind] += 1
                    changed_decision = True
            if changed_decision:
                decisions += 1
                changed_case = True
        cases += changed_case
    return {"cases": cases, "decisions": decisions, "decision_kind_counts": by_kind}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path,
        default=ROOT / "experiments/raw/p10-greedy-factor-20260914/full.json",
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "experiments/reports/p10-greedy-factor-attribution-20260914.json",
    )
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    rows = report["rows"]
    groups = {
        "legacy_six": [row for row in rows if row["case_status"] == "consumed_legacy_six"],
        "persona_independent": [row for row in rows if row["case_id"].startswith("persona:")
                                and row["case_id"].endswith("centered_independent")],
        "persona_aligned": [row for row in rows if row["case_id"].startswith("persona:")
                            and row["case_id"].endswith("negative_persona_aligned")],
        "selected_prior_losses": [row for row in rows if row["case_status"] == "consumed_prior_loss"],
    }
    resources = {}
    for arm in report["config"]["arms"]:
        resources[arm] = {
            "action_failures": sum(row["arms"][arm]["action_failures"] for row in rows),
            "maximum_action_attempts": max(row["arms"][arm]["action_attempts"] for row in rows),
            "minimum_remaining_budget": min(row["arms"][arm]["remaining_budget"] for row in rows),
        }
    compact_rows = []
    for row in rows:
        compact_rows.append({
            "case_id": row["case_id"],
            "case_status": row["case_status"],
            "seed_sha256": row["seed_sha256"],
            "arms": {
                arm: {
                    "score": result["score"],
                    "remaining_budget": result["remaining_budget"],
                    "action_attempts": result["action_attempts"],
                    "action_failures": result["action_failures"],
                    "action_log_sha256": result["action_log_sha256"],
                    "positive_gate_decisions": result["positive_gate_decisions"],
                }
                for arm, result in row["arms"].items()
            },
            "contrasts": row["contrasts"],
        })
    archive_report_path = ROOT / "experiments/reports/archive-attribution-20260913.json"
    archive_report = json.loads(archive_report_path.read_text(encoding="utf-8"))
    archived = {
        row["family"]: row["score"]
        for row in archive_report["rows"]
        if row["archive"] == "starnet-public-greedy-experimental-20260908.zip"
    }
    historical_approximation = {
        row["case_id"]: {
            "pooled_unrestricted": row["arms"]["pooled__unrestricted"]["score"],
            "unchanged_archive": archived[row["case_id"].split(":")[1]],
            "difference": (
                row["arms"]["pooled__unrestricted"]["score"]
                - archived[row["case_id"].split(":")[1]]
            ),
        }
        for row in groups["legacy_six"]
    }
    result = {
        "complete": report["complete"],
        "full_log": {
            "path": str(args.input.relative_to(ROOT)),
            "sha256": digest(args.input),
            "committed": False,
        },
        "config": report["config"],
        "factor_summary": report["summary"],
        "persona_prior_by_consumed_group": {
            name: effect(selected, PERSONA, FIXED) for name, selected in groups.items()
        },
        "pooling_by_consumed_group": {
            name: effect(selected, POOLED, FIXED) for name, selected in groups.items()
        },
        "narrow_negative_cut": {
            "overall": effect(rows, NARROW, FIXED),
            "wins": [
                {
                    "case_id": row["case_id"],
                    "gain": row["arms"][NARROW]["score"] - row["arms"][FIXED]["score"],
                }
                for row in rows
                if row["arms"][NARROW]["score"] - row["arms"][FIXED]["score"] > 1e-8
            ],
        },
        "positive_gate_candidate_set_change": {
            response: candidate_set_change_count(
                rows, f"{response}__direction_roi", f"{response}__full_gate",
            )
            for response in ("pooled", "fixed", "persona")
        },
        "historical_archive_approximation": historical_approximation,
        "resources": resources,
        "rows": compact_rows,
        "production_enabled": False,
        "platform_score": None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "complete": result["complete"],
        "persona_prior_by_consumed_group": result["persona_prior_by_consumed_group"],
        "narrow_negative_cut": result["narrow_negative_cut"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

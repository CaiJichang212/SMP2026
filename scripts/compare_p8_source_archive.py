#!/usr/bin/env python3
"""Verify that diagnostic-only P8 source edits preserve archived decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_submission_archives import CountingLLM, CurrentRulesEnvironment
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.submission.starnet_model import ParticipantSquadModel


P8_ARCHIVE = "starnet-p8-mean-20260913.zip"


def _digest(actions: list[list[object]]) -> str:
    return hashlib.sha256(json.dumps(actions).encode()).hexdigest()


def _run_source(family: str) -> dict[str, object]:
    env = CurrentRulesEnvironment(seed_payload(family, 50, 1))
    llm = CountingLLM(timeout=1, offline_only=True)
    config = json.loads(
        (ROOT / "src/starnet/submission/config.json").read_text(encoding="utf-8")
    )
    model = ParticipantSquadModel(env, config["person"], llm)
    for step in range(1, 121):
        status = model.step()
        if status or env.get_remaining_budget() < 0.5:
            break
    controller = model.controller
    actions = [list(call) for call in env.calls]
    return {
        "family": family,
        "score": env.evaluate(),
        "steps": step,
        "actions": actions,
        "actions_sha256": _digest(actions),
        "p8_mode": getattr(controller, "p8_mode", None),
        "p8_proposals": getattr(controller, "p8_proposals", None),
        "p8_planning_errors": getattr(controller, "p8_planning_errors", None),
        "p8_refresh_reasons": getattr(controller, "p8_refresh_reasons", None),
        "p8_last_planning_error": getattr(controller, "p8_last_planning_error", None),
        "p8_selected_proposals": getattr(controller, "p8_selected_proposals", None),
        "p8_selected_baseline": getattr(controller, "p8_selected_baseline", None),
        "forced_llm_failures": llm.blocked_calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-report", type=Path,
        default=ROOT / "experiments/reports/archive-attribution-20260913.json",
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "experiments/reports/p8-source-archive-equivalence-20260913.json",
    )
    args = parser.parse_args()
    archived_report = json.loads(args.archive_report.read_text(encoding="utf-8"))
    archived = {
        row["family"]: row for row in archived_report["rows"]
        if row["archive"] == P8_ARCHIVE
    }
    rows = []
    for family in SEED_SPECS:
        source = _run_source(family)
        reference = archived[family]
        interventions = [action for action in source["actions"] if action[0] != "scan"]
        archived_interventions = [
            action for action in reference["action_sequence"] if action[0] != "scan"
        ]
        rows.append({
            **{key: value for key, value in source.items() if key != "actions"},
            "archive_score": reference["score"],
            "score_equal": source["score"] == reference["score"],
            "full_sequence_equal": source["actions"] == reference["action_sequence"],
            "intervention_sequence_equal": interventions == archived_interventions,
        })
    result = {
        "schema_version": 1,
        "archive": P8_ARCHIVE,
        "families": list(SEED_SPECS),
        "ranker": "deterministic fallback after forced offline LLM exception",
        "all_scores_equal": all(row["score_equal"] for row in rows),
        "all_full_sequences_equal": all(row["full_sequence_equal"] for row in rows),
        "all_intervention_sequences_equal": all(
            row["intervention_sequence_equal"] for row in rows
        ),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "all_scores_equal", "all_full_sequences_equal", "all_intervention_sequences_equal"
    )}))
    return 0 if result["all_intervention_sequences_equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

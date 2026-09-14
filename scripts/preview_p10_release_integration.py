#!/usr/bin/env python3
"""Preview P10 release identities and activation semantics without enabling it."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_submission import INLINE_MODULES
from scripts.check_p10_research_entry import EXPERIMENT_MODULES, source_collision_audit


P10_MODE_FIELD = "experimental_p10_mode"
P10_MODES = ("plan_only", "response_only", "combined")


def resolve_preview_mode(description, *, certified_mode, report_sha256):
    """Model the proposed absent-default/explicit-unknown activation contract."""
    if certified_mode != "combined" or not isinstance(report_sha256, str) or len(report_sha256) != 64:
        return None
    if not isinstance(description, dict):
        return None
    requested = (
        description[P10_MODE_FIELD]
        if P10_MODE_FIELD in description
        else certified_mode
    )
    return certified_mode if requested == certified_mode else None


def runner_rebuild_options(original):
    """Describe fields that run_baseline_openai must preserve for a fresh controller."""
    p8_mode = getattr(original, "p8_mode", None)
    p10_mode = getattr(original, "p10_experiment_mode", None)
    if p10_mode in P10_MODES and p8_mode == "conservative":
        return {
            "p8_mode": p8_mode,
            "require_stage_envelope": True,
            "experiment_mode": p10_mode,
            "max_structures": getattr(original, "p10_max_structures"),
            "beam_width": getattr(original, "p10_beam_width"),
            "response_estimator": None,
        }
    if p8_mode == "conservative":
        return {"p8_mode": p8_mode, "require_stage_envelope": True}
    return {}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirmation-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ordered = (*INLINE_MODULES[:-1], *EXPERIMENT_MODULES, INLINE_MODULES[-1])
    sources = {}
    python39 = {}
    for relative in ordered:
        path = ROOT / relative
        sources[relative] = digest(path)
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=relative,
                      feature_version=(3, 9))
            python39[relative] = True
        except SyntaxError:
            python39[relative] = False
    confirmation = None
    if args.confirmation_report is not None:
        value = json.loads(args.confirmation_report.read_text(encoding="utf-8"))
        confirmation = {
            "path": str(args.confirmation_report),
            "sha256": digest(args.confirmation_report),
            "selected_variant": value.get("selected_variant"),
            "statistical_gate_passed": value.get("statistical_gate_passed"),
            "release_gate_passed": value.get("release_gate_passed"),
            "release_gate_pending": value.get("release_gate_pending"),
        }
    report = {
        "schema_version": 1,
        "purpose": "Review-only P10 release integration preview",
        "enablement_performed": False,
        "canonical_entry_modified": False,
        "canonical_config_modified": False,
        "canonical_build_modified": False,
        "prospective_inline_order": list(ordered),
        "source_sha256": sources,
        "python39_ast": python39,
        "top_level_collisions": source_collision_audit(ordered),
        "activation_truth_table": {
            "missing_field": resolve_preview_mode({}, certified_mode="combined", report_sha256="a" * 64),
            "explicit_combined": resolve_preview_mode(
                {P10_MODE_FIELD: "combined"}, certified_mode="combined", report_sha256="a" * 64,
            ),
            "explicit_unknown": resolve_preview_mode(
                {P10_MODE_FIELD: "future"}, certified_mode="combined", report_sha256="a" * 64,
            ),
            "explicit_none": resolve_preview_mode(
                {P10_MODE_FIELD: None}, certified_mode="combined", report_sha256="a" * 64,
            ),
            "uncertified": resolve_preview_mode({}, certified_mode=None, report_sha256=None),
        },
        "confirmation": confirmation,
        "ready_to_enable": False,
        "remaining_requirements": [
            "completed statistical gate",
            "sealed real-LLM target-runtime and Python 3.9 entry evidence",
            "new immutable P10 source manifest",
            "reviewed canonical entry, qualification, build, runner, and test patch",
            "final ZIP mock legal-plan approval plus real target-runtime validation",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "enablement_performed": False,
        "python39_sources": sum(python39.values()),
        "collisions": len(report["top_level_collisions"]),
        "statistical_gate_passed": None if confirmation is None else confirmation["statistical_gate_passed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

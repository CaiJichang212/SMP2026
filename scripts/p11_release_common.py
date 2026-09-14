"""Shared fail-closed checks for P11 activation and final ZIP evidence."""

from __future__ import annotations

import ast
import hashlib
import math
from pathlib import Path


P11_METADATA_FIELDS = {
    "P11_CERTIFIED_MODE", "P11_GATE_REPORT_SHA256", "P11_GATE_REPORT_RELATIVE_PATH",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualification_structure(source: str) -> str:
    """Normalize only one literal assignment for each P11 metadata field."""
    tree = ast.parse(source)
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        tree.body[0].value = ast.Constant("<p11-qualification-docstring>")
    counts = {name: 0 for name in P11_METADATA_FIELDS}
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            target = node.targets[0].id
        if target not in P11_METADATA_FIELDS:
            continue
        if not isinstance(node.value, ast.Constant) or not (
            isinstance(node.value.value, str) or node.value.value is None
        ):
            raise ValueError("P11 qualification metadata must be literal str or None")
        counts[target] += 1
        node.value = ast.Constant("<p11-qualification-metadata>")
    if any(count != 1 for count in counts.values()):
        raise ValueError("P11 qualification metadata is incomplete or repeated")
    return ast.dump(tree, include_attributes=False)


def require_unique_archive_members(names) -> set[str]:
    files = [name for name in names if not name.endswith("/")]
    if len(files) != len(set(files)):
        raise ValueError("P11 archive contains duplicate members")
    return set(files)


def normalize_entry(entry: dict) -> dict:
    if not isinstance(entry, dict) or not isinstance(entry.get("result", {}), dict):
        raise ValueError("P11 entry must be an object with an optional result object")
    normalized = dict(entry.get("result", {}))
    for key, value in entry.items():
        if key in ("result", "assembly"):
            continue
        if key in normalized and normalized[key] is not None and value is not None \
                and normalized[key] != value:
            raise ValueError(f"conflicting P11 entry field: {key}")
        if value is not None or key not in normalized:
            normalized[key] = value
    assembly = entry.get("assembly", {})
    if isinstance(assembly, dict):
        normalized.setdefault("model_sha256", assembly.get("model_sha256"))
    return normalized


def validate_prompt_entry(entry: dict, model_sha256: str) -> dict:
    entry = normalize_entry(entry)
    action_sha = entry.get("action_sha256")
    score = entry.get("score")
    if (not isinstance(action_sha, str) or len(action_sha) != 64
            or any(character not in "0123456789abcdef" for character in action_sha.lower())
            or not isinstance(score, (int, float)) or not math.isfinite(float(score))):
        raise ValueError("P11 action identity or score is missing")
    if (entry.get("complete") is not True
            or entry.get("entry_gate_passed") is not True
            or entry.get("model_sha256") != model_sha256
            or entry.get("controller_type") != "PromptLearningRuntimeController"
            or entry.get("p11_experiment_mode") != "prompt_learning"
            or entry.get("p11_enabled") is not True
            or entry.get("p11_calibration_finished") is not True
            or entry.get("p11_selected_prompt_id") not in (1, 2, 3)
            or entry.get("p11_fallback_to_p9") is True
            or entry.get("p11_probe_failures") != 0
            or entry.get("p11_planning_errors") != 0
            or entry.get("p11_errors") != 0
            or entry.get("p11_last_error") is not None
            or entry.get("action_failures") != 0
            or entry.get("p8_planning_errors") != 0
            or entry.get("one_action_per_host_step") is not True
            or entry.get("max_actions_per_host_step") != 1):
        raise ValueError("P11 entry evidence is incomplete, stale, or failed")
    successes = entry.get("p11_probe_successes")
    budget = entry.get("p11_probe_budget")
    if (not isinstance(successes, int) or not 3 <= successes <= 6
            or not isinstance(budget, (int, float)) or budget != 2.0 * successes
            or budget > 12.0):
        raise ValueError("P11 probe resource evidence is invalid")
    dispatches = entry.get(
        "p11_selected_prompt_dispatches",
        entry.get("selected_prompt_dispatch_count", 0),
    )
    if (not isinstance(dispatches, int) or dispatches <= 0
            or entry.get("p11_response_switches", 0) <= 0):
        raise ValueError("P11 entry never used its calibrated prompt")
    entry["selected_prompt_dispatch_count"] = dispatches
    return entry


__all__ = [
    "P11_METADATA_FIELDS", "qualification_structure",
    "normalize_entry", "require_unique_archive_members", "sha256",
    "validate_prompt_entry",
]

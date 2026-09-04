#!/usr/bin/env python3
"""Run small, isolated local-debug probes through only public environment APIs."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Mapping

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.runtime.env_adapter import apply_action_outcome


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "experiments" / "manifests" / "v1-local-probes.json"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "experiments" / "raw" / "v1-local-probes"
DEFAULT_SERVER_URL = "http://8.222.218.162:5000"


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_local_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw_line.strip().partition("=")
        if separator and key == "SMP_SERVER_URL":
            os.environ.setdefault(key, value.strip().strip("\"'"))


def action_from_payload(payload: Mapping[str, object]) -> Action:
    kind = payload.get("kind")
    node = payload.get("target_node_1")
    other = payload.get("target_node_2")
    prompt = payload.get("prompt_id")
    if kind not in {"comm", "cut", "shield"} or isinstance(node, bool) or not isinstance(node, int):
        raise ValueError("invalid probe action")
    if other is not None and (isinstance(other, bool) or not isinstance(other, int)):
        raise ValueError("invalid second action target")
    if prompt is not None and (isinstance(prompt, bool) or not isinstance(prompt, int)):
        raise ValueError("invalid prompt id")
    return Action(kind, node, target_node_2=other, prompt_id=prompt)


def seed_snapshot_matches(seed: Mapping[str, object], board: Blackboard) -> bool:
    expected_nodes = {
        item.get("id"): item
        for item in seed.get("nodes", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), int)
    }
    if set(expected_nodes) != set(board.nodes):
        return False
    for node_id, observed in board.nodes.items():
        expected = expected_nodes[node_id]
        if (
            not math.isclose(float(expected.get("w", math.nan)), observed.w, abs_tol=1e-9)
            or expected.get("persona") != observed.persona
            or expected.get("comm_left") != observed.comm_left
        ):
            return False
    expected_edges = {
        tuple(sorted((int(edge[0]), int(edge[1]))))
        for edge in seed.get("edges", [])
        if isinstance(edge, list) and len(edge) == 2
    }
    return expected_edges == board.edges


def run_probe(
    probe: Mapping[str, object], *, plan_hash: str, server_url: str, timeout: float
) -> dict[str, object]:
    sys.path.insert(0, str(PROJECT_ROOT / "SMP_Starter_Kit"))
    from api_client import RemoteStarNetEnv

    probe_id = probe.get("id")
    seed = probe.get("seed")
    raw_actions = probe.get("actions")
    if not isinstance(probe_id, str) or not isinstance(seed, dict) or not isinstance(raw_actions, list):
        raise ValueError("invalid probe definition")
    started = time.monotonic()
    result: dict[str, object] = {
        "schema_version": 1,
        "session_id": f"{probe_id}-r1",
        "probe_id": probe_id,
        "probe_hash": canonical_hash(probe),
        "plan_hash": plan_hash,
        "seed_payload_hash": canonical_hash(seed),
        "actions": raw_actions,
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    env = RemoteStarNetEnv(api_url=server_url, custom_seed_data=seed, timeout=timeout)
    board = Blackboard()
    initial_budget = env.get_remaining_budget()
    failures = 0
    outcome_rows: list[dict[str, object]] = []
    for item in seed.get("nodes", []):
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), int):
            raise ValueError("invalid probe seed node")
        action = Action("scan", item["id"])
        outcome = apply_action_outcome(env, board, action, env.get_remaining_budget())
        failures += int(not outcome.succeeded)
    snapshot_match = seed_snapshot_matches(seed, board)
    for raw_action in raw_actions:
        if not isinstance(raw_action, Mapping):
            raise ValueError("invalid probe action entry")
        action = action_from_payload(raw_action)
        budget = env.get_remaining_budget()
        legal = is_legal_action(action, board, budget)
        outcome = apply_action_outcome(env, board, action, budget)
        failures += int(not outcome.succeeded)
        outcome_rows.append(
            {
                "action": asdict(action),
                "legal_before_request": legal,
                "succeeded": outcome.succeeded,
                "raw_response": outcome.raw_response,
                "rejected_reason": outcome.rejected_reason,
            }
        )
    before_eval = env.get_remaining_budget()
    error: str | None = None
    try:
        score: float | None = env.trigger_eval()
    except Exception as exc:
        score = None
        error = type(exc).__name__
    result.update(
        {
            "initial_budget": initial_budget,
            "remaining_budget": before_eval,
            "budget_consumed": initial_budget - before_eval,
            "scan_snapshot_match": snapshot_match,
            "action_outcomes": outcome_rows,
            "action_failures": failures,
            "final_score": score,
            "protocol_error": error,
            "comparable": bool(
                error is None
                and failures == 0
                and snapshot_match
                and math.isclose(initial_budget, float(seed["global_setting"]["max_budget"]), abs_tol=1e-9)
            ),
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    )
    return result


def completed_probe(
    path: Path,
    *,
    plan_hash: str,
    probe_hash: str,
    seed_payload_hash: str,
    actions_hash: str,
) -> bool:
    """Accept a resumed session only when it belongs to this exact probe plan."""
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(row, dict) or row.get("plan_hash") != plan_hash or not row.get("completed_at"):
        return False
    if row.get("probe_hash") == probe_hash:
        return True
    # Schema-v1 records created before probe_hash existed remain resumable only
    # when both the seed and the exact action sequence still match.
    return bool(
        row.get("seed_payload_hash") == seed_payload_hash
        and canonical_hash(row.get("actions")) == actions_hash
    )


def save_results(result_dir: Path, rows: list[dict[str, object]]) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        session_path = result_dir / "sessions" / f"{row['session_id']}.json"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    all_rows = []
    for path in sorted((result_dir / "sessions").glob("*.json")):
        all_rows.append(json.loads(path.read_text(encoding="utf-8")))
    (result_dir / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in all_rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("probes"), list):
        raise SystemExit("manifest must contain a probes array")
    load_local_env(PROJECT_ROOT / ".env")
    plan_hash = canonical_hash(manifest)
    result_dir = args.result_dir.resolve() / plan_hash[:16]
    server_url = os.getenv(str(manifest.get("server_url_env", "SMP_SERVER_URL")), DEFAULT_SERVER_URL)
    timeout = float(manifest.get("timeout_seconds", 60))
    probes = list(manifest["probes"])
    random.Random(int(manifest["randomization_seed"])).shuffle(probes)
    new_rows: list[dict[str, object]] = []
    for probe in probes:
        if not isinstance(probe, Mapping) or not isinstance(probe.get("id"), str):
            raise SystemExit("each probe must have a string id")
        session_id = f"{probe['id']}-r1"
        session_path = result_dir / "sessions" / f"{session_id}.json"
        probe_hash = canonical_hash(probe)
        seed = probe.get("seed")
        actions = probe.get("actions")
        if not isinstance(seed, Mapping) or not isinstance(actions, list):
            raise SystemExit("each probe must have a seed object and actions array")
        if args.resume and completed_probe(
            session_path,
            plan_hash=plan_hash,
            probe_hash=probe_hash,
            seed_payload_hash=canonical_hash(seed),
            actions_hash=canonical_hash(actions),
        ):
            continue
        try:
            new_rows.append(run_probe(probe, plan_hash=plan_hash, server_url=server_url, timeout=timeout))
        except Exception as exc:
            new_rows.append(
                {
                    "schema_version": 1,
                    "session_id": session_id,
                    "probe_id": probe["id"],
                    "probe_hash": probe_hash,
                    "plan_hash": plan_hash,
                    "final_score": None,
                    "comparable": False,
                    "protocol_error": type(exc).__name__,
                    "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            )
        save_results(result_dir, new_rows)
    print(f"completed probes={len(probes)} newly_run={len(new_rows)} result_dir={result_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

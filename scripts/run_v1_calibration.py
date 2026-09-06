#!/usr/bin/env python3
"""Collect the preregistered P1/P2 calibration data through public APIs.

This runner is deliberately separate from the submission.  Every session
creates a fresh ``RemoteStarNetEnv``, scans the entire custom micrograph,
performs at most its one preregistered settlement action (or three response
actions), and only then asks the remote test service to evaluate it.  It never
reads the seed's ``r`` field after submission and never accesses a private
environment member.
"""

from __future__ import annotations

import argparse
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
from starnet.policy.actions import Action
from starnet.runtime.env_adapter import apply_action_outcome


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "experiments" / "manifests" / "v1-calibration.json"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "experiments" / "raw" / "v1-calibration"
DEFAULT_SERVER_URL = "http://8.222.218.162:5000"


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_local_env(path: Path) -> None:
    """Load the endpoint override without serialising environment values."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "SMP_SERVER_URL":
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def response_seed(persona: str, initial_w: float) -> dict[str, Any]:
    """One-node seed with response factor held fixed across persona cells."""
    return {
        "global_setting": {"max_budget": 30.0, "max_api_calls": 30},
        "nodes": [{"id": 1, "w": initial_w, "persona": persona, "r": 1.0, "comm_left": 3}],
        "edges": [],
        "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
    }


def _layout_weights(layout: str) -> tuple[float, float, float]:
    if layout == "positive":
        return (-12.0, 16.0, 8.0)
    if layout == "mixed":
        return (-30.0, 8.0, -3.0)
    if layout == "negative_bridge":
        return (-42.0, 12.0, -14.0)
    raise ValueError(f"unknown layout {layout}")


def settlement_seed(family: str, layout: str) -> tuple[dict[str, Any], tuple[int, int]]:
    """Return a small graph where all preregistered action kinds are legal.

    The ``isolated`` family contains an isolated violent target alongside an
    edge.  This preserves the isolated-component counterexample while keeping
    the predeclared cut action executable; no unavailable action is silently
    substituted.
    """
    structures: dict[str, tuple[int, tuple[tuple[int, int], ...], tuple[int, int]]] = {
        "isolated": (3, ((2, 3),), (2, 3)),
        "edge": (2, ((1, 2),), (1, 2)),
        "path3": (3, ((1, 2), (2, 3)), (1, 2)),
        "path5": (5, ((1, 2), (2, 3), (3, 4), (4, 5)), (1, 2)),
        "triangle": (3, ((1, 2), (2, 3), (1, 3)), (1, 2)),
        "star5": (5, ((1, 2), (1, 3), (1, 4), (1, 5)), (1, 2)),
        "disconnected": (4, ((1, 2), (3, 4)), (1, 2)),
    }
    try:
        node_count, edges, cut_edge = structures[family]
    except KeyError as exc:
        raise ValueError(f"unknown graph family {family}") from exc
    violent_w, peace_w, neutral_w = _layout_weights(layout)
    nodes: list[dict[str, Any]] = []
    for node_id in range(1, node_count + 1):
        if node_id == 1:
            nodes.append({"id": node_id, "w": violent_w, "persona": "暴力", "r": 0.2, "comm_left": 3})
        elif node_id == 2:
            nodes.append({"id": node_id, "w": peace_w, "persona": "和平", "r": 1.5, "comm_left": 3})
        else:
            nodes.append({"id": node_id, "w": neutral_w, "persona": "中立", "r": 1.0, "comm_left": 3})
    return (
        {
            "global_setting": {"max_budget": 60.0, "max_api_calls": 120},
            "nodes": nodes,
            "edges": [list(edge) for edge in edges],
            "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
        },
        cut_edge,
    )


def settlement_seed_from_topology(
    family: str, topology: Mapping[str, Any], layout: str,
) -> tuple[dict[str, Any], dict[str, dict[str, object]]]:
    """Build a public custom seed from a manifest-defined topology.

    P2.2 needs topology-disjoint splits, so its graph definitions live in the
    frozen manifest rather than in this historical V1 runner.  Only declared
    actions are emitted; no target is inferred or substituted at runtime.
    """
    node_count, raw_edges, targets = topology.get("node_count"), topology.get("edges"), topology.get("targets")
    if not isinstance(node_count, int) or node_count <= 0 or not isinstance(raw_edges, list) or not isinstance(targets, Mapping):
        raise ValueError(f"invalid topology {family}")
    edges: list[tuple[int, int]] = []
    for edge in raw_edges:
        if not isinstance(edge, list) or len(edge) != 2 or any(not isinstance(node, int) for node in edge):
            raise ValueError(f"invalid edge in topology {family}")
        left, right = edge
        if left == right or not 1 <= left <= node_count or not 1 <= right <= node_count:
            raise ValueError(f"invalid edge endpoint in topology {family}")
        edges.append(tuple(sorted((left, right))))
    if len(edges) != len(set(edges)):
        raise ValueError(f"duplicate edge in topology {family}")
    violent_w, peace_w, neutral_w = _layout_weights(layout)
    nodes = [
        {"id": node_id, "w": violent_w, "persona": "暴力", "r": 0.2, "comm_left": 3}
        if node_id == 1 else
        {"id": node_id, "w": peace_w, "persona": "和平", "r": 1.5, "comm_left": 3}
        if node_id == 2 else
        {"id": node_id, "w": neutral_w, "persona": "中立", "r": 1.0, "comm_left": 3}
        for node_id in range(1, node_count + 1)
    ]
    comm_target, shield_target, cut_edge = targets.get("comm"), targets.get("shield"), targets.get("cut")
    if not isinstance(comm_target, int) or not isinstance(shield_target, int) or not isinstance(cut_edge, list) or len(cut_edge) != 2:
        raise ValueError(f"invalid action targets in topology {family}")
    if comm_target not in range(1, node_count + 1) or shield_target not in range(1, node_count + 1):
        raise ValueError(f"action target outside topology {family}")
    normalized_cut = tuple(sorted((int(cut_edge[0]), int(cut_edge[1]))))
    if normalized_cut not in set(edges):
        raise ValueError(f"cut target is not an edge in topology {family}")
    return (
        {
            "global_setting": {"max_budget": 60.0, "max_api_calls": 120},
            "nodes": nodes,
            "edges": [list(edge) for edge in edges],
            "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
        },
        {
            "control": {"kind": "control"},
            "comm": {"kind": "comm", "target_node_1": comm_target, "prompt_id": 1},
            "cut": {"kind": "cut", "target_node_1": normalized_cut[0], "target_node_2": normalized_cut[1]},
            "shield": {"kind": "shield", "target_node_1": shield_target},
        },
    )


def response_specs(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    protocol = manifest.get("response_protocol")
    if not isinstance(protocol, Mapping):
        raise ValueError("manifest missing response_protocol")
    personas, prompts, initial_w = protocol.get("personas"), protocol.get("prompt_ids"), protocol.get("initial_w")
    repetitions, communications = protocol.get("repetitions"), protocol.get("communications_per_session")
    if (
        not isinstance(personas, list) or not isinstance(prompts, list) or not isinstance(initial_w, list)
        or not isinstance(repetitions, int) or not isinstance(communications, int) or communications <= 0
    ):
        raise ValueError("invalid response_protocol")
    specs: list[dict[str, Any]] = []
    for persona in personas:
        for prompt_id in prompts:
            for value in initial_w:
                for repetition in range(1, repetitions + 1):
                    if not isinstance(persona, str) or not isinstance(prompt_id, int) or not isinstance(value, (int, float)):
                        raise ValueError("invalid response cell")
                    spec = {
                        "kind": "response_session", "persona": persona, "prompt_id": prompt_id,
                        "initial_w": float(value), "repetition": repetition, "communications": communications,
                        "seed": response_seed(persona, float(value)),
                    }
                    spec["session_id"] = f"response-{persona}-p{prompt_id}-w{value}-r{repetition}"
                    spec["spec_hash"] = canonical_hash(spec)
                    specs.append(spec)
    return specs


def settlement_specs(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    protocol = manifest.get("settlement_protocol")
    if not isinstance(protocol, Mapping):
        raise ValueError("manifest missing settlement_protocol")
    families, splits, actions, repetitions = (
        protocol.get("graph_families"), protocol.get("splits"), protocol.get("actions"), protocol.get("repetitions"),
    )
    if not isinstance(splits, list) or not isinstance(actions, list) or not isinstance(repetitions, int):
        raise ValueError("invalid settlement_protocol")
    if set(splits) != {"calibration", "selection", "gate"}:
        raise ValueError("settlement splits must be calibration, selection, gate")
    topologies = protocol.get("topologies")
    layouts_by_split = protocol.get("layouts_by_split")
    if isinstance(topologies, Mapping):
        if not isinstance(families, Mapping) or not isinstance(layouts_by_split, Mapping):
            raise ValueError("topology protocol requires graph_families and layouts_by_split mappings")
        families_by_split = families
    elif isinstance(families, list):
        families_by_split = {str(split): families for split in splits}
        topologies = None
        layouts_by_split = {"calibration": ["positive"], "selection": ["mixed"], "gate": ["negative_bridge"]}
    else:
        raise ValueError("invalid graph_families")
    specs: list[dict[str, Any]] = []
    for split in splits:
        if not isinstance(split, str) or not isinstance(families_by_split.get(split), list) or not isinstance(layouts_by_split.get(split), list):
            raise ValueError("invalid topology split")
        for family in families_by_split[split]:
            if not isinstance(family, str):
                raise ValueError("invalid graph family")
            if topologies is None:
                seed, cut_edge = settlement_seed(family, str(layouts_by_split[split][0]))
                action_map: dict[str, dict[str, object]] = {
                    "control": {"kind": "control"}, "comm": {"kind": "comm", "target_node_1": 2, "prompt_id": 1},
                    "cut": {"kind": "cut", "target_node_1": cut_edge[0], "target_node_2": cut_edge[1]}, "shield": {"kind": "shield", "target_node_1": 1},
                }
                layouts = [str(layouts_by_split[split][0])]
            else:
                topology = topologies.get(family)
                if not isinstance(topology, Mapping):
                    raise ValueError(f"missing topology {family}")
                layouts = layouts_by_split[split]
            for layout in layouts:
                if not isinstance(layout, str):
                    raise ValueError("invalid layout")
                if topologies is not None:
                    seed, action_map = settlement_seed_from_topology(family, topology, layout)
                graph_id = f"{family}-{layout}"
                for action_name in actions:
                    if action_name not in action_map:
                        raise ValueError(f"unknown settlement action {action_name}")
                    for repetition in range(1, repetitions + 1):
                        spec = {
                            "kind": "settlement_session", "split": split, "graph_id": graph_id,
                            "action": action_map[action_name], "repetition": repetition, "seed": seed,
                        }
                        spec["session_id"] = f"settlement-{graph_id}-{action_name}-r{repetition}"
                        spec["spec_hash"] = canonical_hash(spec)
                        specs.append(spec)
    return specs


def stable_plan(manifest: Mapping[str, Any], phase: str) -> list[dict[str, Any]]:
    response = response_specs(manifest) if phase in {"all", "response"} else []
    settlement = settlement_specs(manifest) if phase in {"all", "settlement"} else []
    return response + settlement


def snapshot_matches_seed(seed: Mapping[str, Any], board: Blackboard) -> bool:
    raw_nodes, raw_edges = seed.get("nodes"), seed.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return False
    expected_nodes = {item.get("id"): item for item in raw_nodes if isinstance(item, Mapping)}
    if set(expected_nodes) != set(board.nodes):
        return False
    for node_id, node in board.nodes.items():
        expected = expected_nodes[node_id]
        if (
            not math.isclose(node.w, float(expected.get("w", math.nan)), abs_tol=1e-9)
            or node.persona != expected.get("persona")
            or node.comm_left != expected.get("comm_left")
        ):
            return False
    expected_edges = {tuple(sorted((int(left), int(right)))) for left, right in raw_edges}
    return expected_edges == board.edges


def action_from_payload(payload: Mapping[str, object]) -> Action | None:
    kind = payload.get("kind")
    if kind == "control":
        return None
    node_1 = payload.get("target_node_1")
    if not isinstance(kind, str) or not isinstance(node_1, int):
        raise ValueError("invalid action payload")
    node_2, prompt_id = payload.get("target_node_2"), payload.get("prompt_id")
    return Action(kind, node_1, node_2 if isinstance(node_2, int) else None, prompt_id if isinstance(prompt_id, int) else None)


def _base_result(spec: Mapping[str, object], plan_hash: str) -> dict[str, Any]:
    return {
        "schema_version": 1, "session_id": spec["session_id"], "spec_hash": spec["spec_hash"],
        "plan_hash": plan_hash, "session_kind": spec["kind"], "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "seed_payload_hash": canonical_hash(spec["seed"]),
    }


def _new_env(server_url: str, seed: Mapping[str, Any], timeout: float) -> Any:
    sys.path.insert(0, str(PROJECT_ROOT / "SMP_Starter_Kit"))
    from api_client import RemoteStarNetEnv
    return RemoteStarNetEnv(api_url=server_url, custom_seed_data=seed, timeout=timeout)


def _scan_all(env: Any, seed: Mapping[str, Any]) -> tuple[Blackboard, int]:
    board, failures = Blackboard(), 0
    for raw_node in seed["nodes"]:
        node_id = raw_node["id"]
        action = Action("scan", node_id)
        outcome = apply_action_outcome(env, board, action, env.get_remaining_budget())
        failures += int(not outcome.succeeded)
    return board, failures


def run_response_session(spec: Mapping[str, Any], *, plan_hash: str, server_url: str, timeout: float) -> dict[str, Any]:
    started, result, seed = time.monotonic(), _base_result(spec, plan_hash), spec["seed"]
    assert isinstance(seed, Mapping)
    env = _new_env(server_url, seed, timeout)
    initial_budget = env.get_remaining_budget()
    board, failures = _scan_all(env, seed)
    scan_match = snapshot_matches_seed(seed, board)
    rows: list[dict[str, Any]] = []
    for turn in range(1, int(spec["communications"]) + 1):
        old_w = board.nodes.get(1).w if 1 in board.nodes else None
        action = Action("comm", 1, prompt_id=int(spec["prompt_id"]))
        outcome = apply_action_outcome(env, board, action, env.get_remaining_budget())
        failures += int(not outcome.succeeded)
        new_w = board.nodes.get(1).w if 1 in board.nodes else None
        rows.append({
            "kind": "response", "session_id": spec["session_id"], "plan_hash": plan_hash,
            "persona": spec["persona"], "prompt_id": spec["prompt_id"], "initial_w": spec["initial_w"],
            "repetition": spec["repetition"], "turn": turn, "success": outcome.succeeded,
            "delta_w": (new_w - old_w) if outcome.succeeded and old_w is not None and new_w is not None else None,
            "raw_response": outcome.raw_response,
        })
    before_eval = env.get_remaining_budget()
    error: str | None = None
    try:
        score = env.trigger_eval()
    except Exception as exc:
        score, error = None, type(exc).__name__
    comparable = bool(
        error is None and failures == 0 and scan_match and math.isclose(initial_budget, float(seed["global_setting"]["max_budget"]), abs_tol=1e-9)
        and isinstance(score, (int, float)) and math.isfinite(float(score))
    )
    for row in rows:
        row.update({"comparable": comparable, "final_score": score, "protocol_error": error})
    result.update({
        "persona": spec["persona"], "prompt_id": spec["prompt_id"], "initial_w": spec["initial_w"], "repetition": spec["repetition"],
        "initial_budget": initial_budget, "remaining_budget": before_eval, "budget_consumed": initial_budget - before_eval,
        "scan_snapshot_match": scan_match, "action_failures": failures, "final_score": score, "protocol_error": error,
        "comparable": comparable, "response_rows": rows, "elapsed_seconds": round(time.monotonic() - started, 6),
    })
    return result


def run_settlement_session(spec: Mapping[str, Any], *, plan_hash: str, server_url: str, timeout: float) -> dict[str, Any]:
    started, result, seed = time.monotonic(), _base_result(spec, plan_hash), spec["seed"]
    assert isinstance(seed, Mapping)
    env = _new_env(server_url, seed, timeout)
    initial_budget = env.get_remaining_budget()
    board, failures = _scan_all(env, seed)
    scan_match = snapshot_matches_seed(seed, board)
    before_snapshot = board.snapshot()
    raw_action = spec["action"]
    assert isinstance(raw_action, Mapping)
    action = action_from_payload(raw_action)
    observed_delta: float | None = None
    raw_response: object | None = None
    if action is not None:
        old_w = board.nodes.get(action.target_node_1).w if action.kind == "comm" and action.target_node_1 in board.nodes else None
        outcome = apply_action_outcome(env, board, action, env.get_remaining_budget())
        raw_response = outcome.raw_response
        failures += int(not outcome.succeeded)
        if action.kind == "comm" and outcome.succeeded and old_w is not None and action.target_node_1 in board.nodes:
            observed_delta = board.nodes[action.target_node_1].w - old_w
    before_eval = env.get_remaining_budget()
    error: str | None = None
    try:
        score = env.trigger_eval()
    except Exception as exc:
        score, error = None, type(exc).__name__
    comparable = bool(
        error is None and failures == 0 and scan_match and math.isclose(initial_budget, float(seed["global_setting"]["max_budget"]), abs_tol=1e-9)
        and isinstance(score, (int, float)) and math.isfinite(float(score))
    )
    settlement_row = {
        "kind": "settlement", "session_id": spec["session_id"], "plan_hash": plan_hash, "split": spec["split"],
        "graph_id": spec["graph_id"], "repetition": spec["repetition"], "before_snapshot": before_snapshot,
        "action": dict(raw_action), "observed_delta": observed_delta, "final_score": score,
        "terminal_hash": canonical_hash(board.snapshot()), "comparable": comparable, "protocol_error": error,
        "action_failures": failures, "raw_response": raw_response,
    }
    result.update({
        "split": spec["split"], "graph_id": spec["graph_id"], "action": dict(raw_action), "repetition": spec["repetition"],
        "initial_budget": initial_budget, "remaining_budget": before_eval, "budget_consumed": initial_budget - before_eval,
        "scan_snapshot_match": scan_match, "action_failures": failures, "final_score": score, "protocol_error": error,
        "comparable": comparable, "settlement_row": settlement_row, "elapsed_seconds": round(time.monotonic() - started, 6),
    })
    return result


def completed(path: Path, spec: Mapping[str, Any]) -> bool:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(row.get("spec_hash") == spec["spec_hash"] and row.get("completed_at"))


def save(result_dir: Path, result: dict[str, Any]) -> None:
    result["completed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sessions = result_dir / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    path = sessions / f"{result['session_id']}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    all_sessions = [json.loads(item.read_text(encoding="utf-8")) for item in sorted(sessions.glob("*.json"))]
    (result_dir / "results.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in all_sessions), encoding="utf-8"
    )
    rows: list[dict[str, Any]] = []
    for item in all_sessions:
        if item.get("session_kind") == "response_session":
            rows.extend(row for row in item.get("response_rows", []) if isinstance(row, dict))
        elif isinstance(item.get("settlement_row"), dict):
            rows.append(item["settlement_row"])
    (result_dir / "calibration.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in rows), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--phase", choices=("all", "response", "settlement"), default="all")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-new-sessions", type=int)
    args = parser.parse_args()
    if args.max_new_sessions is not None and args.max_new_sessions <= 0:
        raise SystemExit("--max-new-sessions must be positive")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("manifest root must be an object")
    plan_hash = canonical_hash(manifest)
    result_dir = args.result_dir.resolve() / plan_hash[:16]
    load_local_env(PROJECT_ROOT / ".env")
    server_url = os.getenv(str(manifest.get("server_url_env", "SMP_SERVER_URL")), DEFAULT_SERVER_URL)
    timeout = float(manifest.get("timeout_seconds", 60))
    plan = stable_plan(manifest, args.phase)
    random.Random(int(manifest["randomization_seed"]) + {"all": 0, "response": 1, "settlement": 2}[args.phase]).shuffle(plan)
    if args.dry_run:
        response_count = sum(item["kind"] == "response_session" for item in plan)
        print(f"planned={len(plan)} response_sessions={response_count} settlement_sessions={len(plan) - response_count}")
        return 0
    newly_run = 0
    for spec in plan:
        session_path = result_dir / "sessions" / f"{spec['session_id']}.json"
        if args.resume and completed(session_path, spec):
            continue
        if args.max_new_sessions is not None and newly_run >= args.max_new_sessions:
            break
        try:
            result = (
                run_response_session(spec, plan_hash=plan_hash, server_url=server_url, timeout=timeout)
                if spec["kind"] == "response_session"
                else run_settlement_session(spec, plan_hash=plan_hash, server_url=server_url, timeout=timeout)
            )
        except Exception as exc:
            result = _base_result(spec, plan_hash)
            result.update({"comparable": False, "final_score": None, "protocol_error": type(exc).__name__, "elapsed_seconds": None})
        save(result_dir, result)
        newly_run += 1
    print(f"planned={len(plan)} newly_run={newly_run} result_dir={result_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

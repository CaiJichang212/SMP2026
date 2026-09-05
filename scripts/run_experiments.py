#!/usr/bin/env python3
"""Run the V0 reproducibility gate and parameter matrix against fresh sessions.

Credentials are read only from ``.env``/environment and are never serialized.
Use ``--dry-run`` to inspect the deterministic manifest-derived stable plan.
"""

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
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping

import requests

from starnet.experiments.seeds import all_seed_payloads
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.config import PolicyConfig, PolicyMode
from starnet.policy.calibration import DEFAULT_CALIBRATION_PROFILE
from starnet.runtime.controller import RuntimeController
from starnet.runtime.env_adapter import apply_action_outcome
from starnet.runtime.trace import RuntimeTrace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "experiments" / "manifests" / "v0-matrix.json"
DEFAULT_RESULTS = PROJECT_ROOT / "experiments" / "raw" / "v0-matrix"
DEFAULT_SERVER_URL = "http://8.222.218.162:5000"
GATE_POLICIES = ("scan_only", "shield_2", "communicate_1_3_4", "historical_v0_terminal")
UNSTABLE_SEEDS = ("ba_negative_hubs", "sbm_negative_bridges", "sbm_violent_cluster")
BASELINE_METADATA = {
    "project_commit": "c26e6f3",
    "casevo_commit": "d3b8d1f",
    "python": "3.12.3",
    "uv": "0.12.9",
}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_local_env(path: Path) -> None:
    """Load only known local configuration names without printing their values."""
    if not path.is_file():
        return
    allowed = {"SMP_LLM_API_KEY", "SMP_LLM_BASE_URL", "SMP_LLM_MODEL", "SMP_SERVER_URL"}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in allowed:
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def four_node_fixture() -> dict[str, Any]:
    return {
        "global_setting": {"max_budget": 60.0, "max_api_calls": 120},
        "nodes": [
            {"id": 1, "w": 10.0, "persona": "和平", "r": 1.5, "comm_left": 3},
            {"id": 2, "w": -40.0, "persona": "暴力", "r": 0.2, "comm_left": 3},
            {"id": 3, "w": 0.0, "persona": "中立", "r": 1.0, "comm_left": 3},
            {"id": 4, "w": 15.0, "persona": "和平", "r": 1.2, "comm_left": 3},
        ],
        "edges": [[1, 2], [2, 3], [3, 4], [1, 4]],
        "prompts": {"1": 15.0, "2": 10.0, "3": -5.0},
    }


def variant_config(name: str) -> PolicyConfig:
    """Map each protocol variant to a fully explicit immutable configuration."""
    common = {"max_llm_calls": 0}
    configs = {
        "scan_only": PolicyConfig(stop_after_scan=True, **common),
        "v0_deterministic": PolicyConfig(**common),
        "v0_llm3": PolicyConfig(max_llm_calls=3),
        "risk_loose": PolicyConfig(shield_threshold=0.35, cut_threshold=0.10, **common),
        "risk_strict": PolicyConfig(shield_threshold=0.75, cut_threshold=0.35, **common),
        "mixed_raw_roi": PolicyConfig(p0_exclusive=False, mixed_raw_roi=True, **common),
        "communicate_only": PolicyConfig(enable_shield=False, enable_cut=False, **common),
        "risk_only": PolicyConfig(enable_communicate=False, **common),
        "v1_cmg": PolicyConfig(policy_mode=PolicyMode.V1_CMG, **common),
    }
    try:
        return configs[name]
    except KeyError as exc:
        raise ValueError(f"unknown variant {name}") from exc


def session_spec(
    *, seed_id: str, variant: str, phase: str, repetition: int = 1, block: int | None = None
) -> dict[str, Any]:
    config = asdict(variant_config(variant)) if phase == "main" else {"gate_policy": variant}
    if variant == "v1_cmg" and phase == "main":
        # Profile content is strategy content.  A changed/fail-closed profile
        # must invalidate resumed sessions even inside the same manifest tree.
        config["calibration_profile_hash"] = DEFAULT_CALIBRATION_PROFILE.profile_hash
        config["calibration_profile_verified"] = DEFAULT_CALIBRATION_PROFILE.verified
    spec = {
        "phase": phase,
        "seed_id": seed_id,
        "variant": variant,
        "repetition": repetition,
        "block": block,
        "config": config,
    }
    spec["session_id"] = f"{phase}-{seed_id}-{variant}-r{repetition}"
    spec["spec_hash"] = canonical_hash(spec)
    return spec


def stable_plan(manifest: Mapping[str, object]) -> list[dict[str, Any]]:
    """Return the fixed 20-session gate plus the manifest-defined matrix."""
    gate = [
        session_spec(seed_id="four_node_fixture", variant=policy, phase="gate", repetition=block, block=block)
        for block in range(1, 6)
        for policy in GATE_POLICIES
    ]
    seeds = manifest.get("main_seeds")
    variants = manifest.get("variants")
    if not isinstance(seeds, list) or not isinstance(variants, list):
        raise ValueError("manifest must provide main_seeds and variants arrays")
    repetitions = manifest.get("main_repetitions", 1)
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
        raise ValueError("main_repetitions must be a positive integer")
    main = [
        session_spec(seed_id=str(seed), variant=str(variant), phase="main", repetition=repetition)
        for seed in seeds
        for variant in variants
        for repetition in range(1, repetitions + 1)
    ]
    return gate + main


def unstable_plan(manifest: Mapping[str, object]) -> list[dict[str, Any]]:
    variants = manifest.get("variants")
    if not isinstance(variants, list):
        raise ValueError("manifest must provide variants")
    return [
        session_spec(seed_id=seed, variant=str(variant), phase="main", repetition=repetition)
        for seed in UNSTABLE_SEEDS
        for variant in variants
        for repetition in (1, 2)
    ]


def randomized_order(sessions: Iterable[dict[str, Any]], randomization_seed: int) -> list[dict[str, Any]]:
    ordered = list(sessions)
    random.Random(randomization_seed).shuffle(ordered)
    return ordered


def snapshot_hash(board: Blackboard) -> str:
    return canonical_hash(board.snapshot())


def seed_snapshot_matches(seed: Mapping[str, object], board: Blackboard) -> bool:
    nodes = seed.get("nodes")
    edges = seed.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list) or len(nodes) != len(board.nodes):
        return False
    expected_nodes = {
        item.get("id"): item
        for item in nodes
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
    expected_edges = {tuple(sorted((int(edge[0]), int(edge[1])))) for edge in edges if isinstance(edge, list) and len(edge) == 2}
    return expected_edges == board.edges


class ActionCollector:
    """Trace sink that retains only safe action identifiers and scan snapshots."""

    def __init__(self) -> None:
        self.actions: list[dict[str, object]] = []

    def emit(self, record: Mapping[str, object]) -> None:
        if record.get("event") != "action.requested":
            return
        data = record.get("data")
        if isinstance(data, Mapping) and isinstance(data.get("action"), Mapping):
            self.actions.append(dict(data["action"]))


def llm_ranker(timeout: float) -> Callable[[dict[str, Any]], object]:
    api_key = os.getenv("SMP_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("SMP_LLM_API_KEY is required only for v0_llm3")
    base_url = os.getenv("SMP_LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("SMP_LLM_MODEL", "deepseek-v4-flash")

    def rank(payload: dict[str, Any]) -> object:
        prompt = (
            "Return JSON only: {\"mode\":\"balanced\",\"candidate_ids\":[...]}. "
            "You may order only these candidate IDs; do not create actions.\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("LLM response had no chat completion") from exc

    return rank


def _result_base(spec: Mapping[str, object], seed: Mapping[str, object]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": spec["session_id"],
        "spec_hash": spec["spec_hash"],
        "phase": spec["phase"],
        "seed_id": spec["seed_id"],
        "variant": spec["variant"],
        "repetition": spec["repetition"],
        "config": spec["config"],
        "plan_hash": spec.get("plan_hash"),
        "matrix_branch": spec.get("matrix_branch"),
        "baseline": BASELINE_METADATA,
        "seed_payload_hash": canonical_hash(seed),
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def run_main_session(
    spec: Mapping[str, object], seed: dict[str, Any], *, server_url: str, timeout: float
) -> dict[str, Any]:
    """Run one configuration in a fresh server session using public APIs only."""
    sys.path.insert(0, str(PROJECT_ROOT / "SMP_Starter_Kit"))
    from api_client import RemoteStarNetEnv

    started = time.monotonic()
    result = _result_base(spec, seed)
    env = RemoteStarNetEnv(api_url=server_url, custom_seed_data=seed, timeout=timeout)
    initial_budget = env.get_remaining_budget()
    config = variant_config(str(spec["variant"]))
    ranker = llm_ranker(timeout) if str(spec["variant"]) == "v0_llm3" else None
    controller = RuntimeController(env, ranker, initial_budget=initial_budget, node_count=len(seed["nodes"]), config=config)
    collector = ActionCollector()
    controller.attach_trace(RuntimeTrace(run_id=str(spec["session_id"]), seed_id=str(spec["seed_id"]), sinks=[collector]))
    scan_hash: str | None = None
    scan_match = False
    protocol_error: str | None = None
    while not controller.stopped:
        controller.step()
        if len(controller.blackboard.nodes) == len(seed["nodes"]) and scan_hash is None:
            scan_hash = snapshot_hash(controller.blackboard)
            scan_match = seed_snapshot_matches(seed, controller.blackboard)
        if controller.last_action_error is not None:
            protocol_error = controller.last_action_error
            controller.stop_for_runner_error()
            break
    pre_eval_budget = env.get_remaining_budget()
    score: float | None = None
    try:
        score = env.trigger_eval()
    except Exception as exc:
        protocol_error = protocol_error or type(exc).__name__
    action_counts = {kind: sum(action.get("kind") == kind for action in collector.actions) for kind in ("scan", "comm", "cut", "shield")}
    result.update(
        {
            "initial_budget": initial_budget,
            "final_score": score,
            "budget_consumed": initial_budget - pre_eval_budget,
            "remaining_budget": pre_eval_budget,
            "action_counts": action_counts,
            "step_count": controller.step_number,
            "llm_calls": controller.llm_calls,
            "scan_snapshot_hash": scan_hash,
            "final_state_hash": snapshot_hash(controller.blackboard),
            "scan_snapshot_match": scan_match,
            "action_failures": controller.action_failures,
            "protocol_error": protocol_error,
            "stop_reason": controller.stop_reason.value if controller.stop_reason else None,
            "comparable": bool(
                scan_match
                and protocol_error is None
                and controller.action_failures == 0
                and math.isclose(initial_budget, 100.0, abs_tol=1e-9)
            ),
            "elapsed_seconds": round(time.monotonic() - started, 6),
        }
    )
    return result


def _gate_actions(policy: str) -> list[Action]:
    communications = [Action("comm", node, prompt_id=1) for node in (1, 3, 4) for _ in range(3)]
    if policy == "scan_only":
        return []
    if policy == "shield_2":
        return [Action("shield", 2)]
    if policy == "communicate_1_3_4":
        return communications
    if policy == "historical_v0_terminal":
        return [Action("shield", 2), *communications]
    raise ValueError(f"unknown gate policy {policy}")


def run_gate_session(
    spec: Mapping[str, object], seed: dict[str, Any], *, server_url: str, timeout: float
) -> dict[str, Any]:
    sys.path.insert(0, str(PROJECT_ROOT / "SMP_Starter_Kit"))
    from api_client import RemoteStarNetEnv

    started = time.monotonic()
    result = _result_base(spec, seed)
    env = RemoteStarNetEnv(api_url=server_url, custom_seed_data=seed, timeout=timeout)
    board = Blackboard()
    initial_budget = env.get_remaining_budget()
    failures = 0
    for node_id in range(1, 5):
        action = Action("scan", node_id)
        if not is_legal_action(action, board, env.get_remaining_budget()):
            failures += 1
            continue
        outcome = apply_action_outcome(env, board, action, env.get_remaining_budget())
        failures += int(not outcome.succeeded)
    scan_hash = snapshot_hash(board)
    scan_match = seed_snapshot_matches(seed, board)
    completed_actions: list[Action] = [Action("scan", node) for node in range(1, 5)]
    for action in _gate_actions(str(spec["variant"])):
        budget = env.get_remaining_budget()
        if not is_legal_action(action, board, budget):
            failures += 1
            continue
        outcome = apply_action_outcome(env, board, action, budget)
        completed_actions.append(action)
        failures += int(not outcome.succeeded)
    pre_eval_budget = env.get_remaining_budget()
    score: float | None = None
    error: str | None = None
    try:
        score = env.trigger_eval()
    except Exception as exc:
        error = type(exc).__name__
    result.update(
        {
            "initial_budget": initial_budget,
            "final_score": score,
            "budget_consumed": initial_budget - pre_eval_budget,
            "remaining_budget": pre_eval_budget,
            "action_counts": {kind: sum(action.kind == kind for action in completed_actions) for kind in ("scan", "comm", "cut", "shield")},
            "step_count": len(completed_actions),
            "llm_calls": 0,
            "scan_snapshot_hash": scan_hash,
            "final_state_hash": snapshot_hash(board),
            "scan_snapshot_match": scan_match,
            "action_failures": failures,
            "protocol_error": error,
            "stop_reason": "script_completed",
            "comparable": bool(
                scan_match
                and error is None
                and failures == 0
                and math.isclose(initial_budget, 60.0, abs_tol=1e-9)
            ),
            "elapsed_seconds": round(time.monotonic() - started, 6),
        }
    )
    return result


def gate_is_stable(results: Iterable[Mapping[str, object]]) -> tuple[bool, dict[str, float]]:
    """Check score spread and both state hashes for each fixed terminal policy."""
    groups: dict[str, list[Mapping[str, object]]] = {}
    for result in results:
        groups.setdefault(str(result.get("variant")), []).append(result)
    spreads: dict[str, float] = {}
    stable = True
    for policy in GATE_POLICIES:
        rows = groups.get(policy, [])
        scores = [float(row["final_score"]) for row in rows if isinstance(row.get("final_score"), (int, float))]
        hashes = {str(row.get("final_state_hash")) for row in rows}
        snapshots = {str(row.get("scan_snapshot_hash")) for row in rows}
        comparable = all(row.get("comparable") is True for row in rows)
        if len(rows) != 5 or not comparable or len(scores) != 5 or len(hashes) != 1 or len(snapshots) != 1:
            stable = False
            spreads[policy] = math.inf
            continue
        median = sorted(scores)[len(scores) // 2]
        spread = (max(scores) - min(scores)) / max(1.0, abs(median))
        spreads[policy] = spread
        stable = stable and spread <= 0.02
    return stable, spreads


def _result_path(result_dir: Path, session_id: str) -> Path:
    return result_dir / "sessions" / f"{session_id}.json"


def result_namespace(result_root: Path, manifest: Mapping[str, object]) -> Path:
    """Separate records whenever any manifest input changes."""
    return result_root / canonical_hash(manifest)[:16]


def contextualize_spec(
    spec: Mapping[str, Any], *, plan_hash: str, matrix_branch: str
) -> dict[str, Any]:
    """Attach non-selection metadata without changing the candidate spec hash."""
    return {**spec, "plan_hash": plan_hash, "matrix_branch": matrix_branch}


def completed_result(path: Path, spec_hash: str, seed_payload_hash: str) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return (
        data
        if data.get("spec_hash") == spec_hash
        and data.get("seed_payload_hash") == seed_payload_hash
        and data.get("completed_at")
        else None
    )


def save_result(result_dir: Path, result: dict[str, Any]) -> None:
    result["completed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path = _result_path(result_dir, str(result["session_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    rows: list[dict[str, Any]] = []
    for session_file in sorted(path.parent.glob("*.json")):
        try:
            rows.append(json.loads(session_file.read_text(encoding="utf-8")))
        except ValueError:
            continue
    (result_dir / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    columns = ["session_id", "phase", "seed_id", "variant", "repetition", "final_score", "comparable", "step_count", "llm_calls", "remaining_budget", "action_failures", "elapsed_seconds"]
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(json.dumps(row.get(column, ""), ensure_ascii=False) for column in columns))
    (result_dir / "results.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def adopt_legacy_successes(
    legacy_path: Path,
    *,
    plan: Iterable[Mapping[str, object]],
    plan_dir: Path,
    plan_hash: str,
    payloads: Mapping[str, Mapping[str, object]],
) -> int:
    """Copy only successful legacy records into the namespaced result layout.

    A legacy record is accepted only when its immutable session and seed hashes
    match the current plan.  Protocol-error records are deliberately omitted so
    ``--resume`` will rerun them rather than treating them as completed.
    """
    try:
        legacy_rows = [json.loads(line) for line in legacy_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read legacy results: {legacy_path}") from exc
    by_session = {
        row.get("session_id"): row
        for row in legacy_rows
        if isinstance(row, dict) and isinstance(row.get("session_id"), str)
    }
    adopted = 0
    for raw_spec in plan:
        session_id = str(raw_spec["session_id"])
        row = by_session.get(session_id)
        if row is None or row.get("spec_hash") != raw_spec["spec_hash"]:
            raise ValueError(f"legacy record does not match planned session: {session_id}")
        seed_id = str(raw_spec["seed_id"])
        if row.get("seed_payload_hash") != canonical_hash(payloads[seed_id]):
            raise ValueError(f"legacy record has different seed payload: {session_id}")
        if not row.get("comparable"):
            continue
        branch = "gate" if raw_spec["phase"] == "gate" else "stable"
        result = {
            **row,
            "plan_hash": plan_hash,
            "matrix_branch": branch,
            "baseline": row.get("baseline", BASELINE_METADATA),
        }
        save_result(plan_dir / branch, result)
        adopted += 1
    return adopted


def run_preflight() -> None:
    commands = [
        [sys.executable, "scripts/build_submission.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    ]
    for command in commands:
        completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        if completed.returncode:
            raise RuntimeError("preflight failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--timeout", type=float, help="per-request timeout in seconds")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--adopt-legacy",
        type=Path,
        help="migrate matching successful legacy JSONL records; protocol errors are rerun",
    )
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument(
        "--max-new-sessions",
        type=int,
        help="bounded resumable batch size; useful when the runner is externally time-sliced",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("manifest root must be an object")
    plan = stable_plan(manifest)
    if args.dry_run:
        for spec in randomized_order(plan, int(manifest["randomization_seed"])):
            print(json.dumps(spec, ensure_ascii=False, sort_keys=True))
        main_count = sum(spec["phase"] == "main" for spec in plan)
        print(f"dry-run sessions={len(plan)} (gate={len(plan) - main_count}, stable-matrix={main_count})")
        return 0
    load_local_env(PROJECT_ROOT / ".env")
    if not args.skip_preflight:
        run_preflight()
    timeout = float(args.timeout if args.timeout is not None else manifest.get("timeout_seconds", 60))
    if timeout <= 0:
        raise SystemExit("--timeout must be positive")
    result_root = args.result_dir.resolve()
    plan_hash = canonical_hash(manifest)
    plan_dir = result_namespace(result_root, manifest)
    plan_dir.mkdir(parents=True, exist_ok=True)
    server_url = os.getenv(str(manifest.get("server_url_env", "SMP_SERVER_URL")), DEFAULT_SERVER_URL)
    payloads = all_seed_payloads()
    payloads["four_node_fixture"] = four_node_fixture()
    if args.adopt_legacy is not None:
        adopted = adopt_legacy_successes(
            args.adopt_legacy,
            plan=plan,
            plan_dir=plan_dir,
            plan_hash=plan_hash,
            payloads=payloads,
        )
        print(f"adopted legacy successes={adopted}; result_dir={plan_dir}")
    if args.max_new_sessions is not None and args.max_new_sessions <= 0:
        raise SystemExit("--max-new-sessions must be positive")
    new_sessions = 0

    def run_specs(specs: list[dict[str, Any]], *, matrix_branch: str) -> list[dict[str, Any]]:
        nonlocal new_sessions
        branch_dir = plan_dir / matrix_branch
        rows: list[dict[str, Any]] = []
        for raw_spec in randomized_order(specs, int(manifest["randomization_seed"])):
            spec = contextualize_spec(raw_spec, plan_hash=plan_hash, matrix_branch=matrix_branch)
            seed = payloads[str(spec["seed_id"])]
            existing = (
                completed_result(
                    _result_path(branch_dir, str(spec["session_id"])),
                    str(spec["spec_hash"]),
                    canonical_hash(seed),
                )
                if args.resume
                else None
            )
            if existing is not None:
                rows.append(existing)
                continue
            if args.max_new_sessions is not None and new_sessions >= args.max_new_sessions:
                break
            try:
                row = run_gate_session(spec, seed, server_url=server_url, timeout=timeout) if spec["phase"] == "gate" else run_main_session(spec, seed, server_url=server_url, timeout=timeout)
            except Exception as exc:
                row = _result_base(spec, seed)
                row.update({"final_score": None, "comparable": False, "protocol_error": type(exc).__name__, "elapsed_seconds": None})
            save_result(branch_dir, row)
            rows.append(row)
            new_sessions += 1
        return rows

    gate_specs = [spec for spec in plan if spec["phase"] == "gate"]
    gate_results = run_specs(gate_specs, matrix_branch="gate")
    stable, spreads = gate_is_stable(gate_results)
    gate_complete = len(gate_results) == len(gate_specs)
    (plan_dir / "gate_status.json").write_text(
        json.dumps(
            {
                "plan_hash": plan_hash,
                "gate_complete": gate_complete,
                "stable": stable if gate_complete else None,
                "score_spreads": spreads,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if not gate_complete:
        print(f"gate incomplete; newly_run={new_sessions}; result_dir={plan_dir}")
        return 0
    matrix_branch = "stable" if stable else "unstable"
    main_specs = [spec for spec in plan if spec["phase"] == "main"] if stable else unstable_plan(manifest)
    run_specs(main_specs, matrix_branch=matrix_branch)
    print(
        f"completed gate_stable={stable}; main_sessions={len(main_specs)}; "
        f"newly_run={new_sessions}; result_dir={plan_dir / matrix_branch}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

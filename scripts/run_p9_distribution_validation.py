#!/usr/bin/env python3
"""Run the P9 resampled-distribution development cohort with three controls."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
from tempfile import TemporaryDirectory
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.compare_submission_archives import (
    CountingLLM,
    CurrentRulesEnvironment,
    extract_submission,
)
from scripts.build_submission import INLINE_MODULES
from starnet.experiments.p9_distribution_seeds import (
    CONFIRMATION_REPETITIONS,
    DEVELOPMENT_REPETITIONS,
    FAMILIES,
    SHIFT_STRATA,
    seed_payload,
)
from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.p8_experiment import public_board_salt
from starnet.policy.p9_coverage_experiment import choose_coverage_action
from starnet.runtime.env_adapter import apply_action_outcome
from starnet.submission.starnet_model import ParticipantSquadModel as CurrentParticipantSquadModel


ARCHIVES = {
    "official_best_experimental": "starnet-public-greedy-experimental-20260908.zip",
    "p8_submitted": "starnet-p8-mean-20260913.zip",
}
COVERAGE_ARM = "coverage13"
CURRENT_ARM = "bounded_source"
MECHANISM_REPORT = ROOT / "experiments/reports/p9-response-bounds-probe-20260913.json"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _seed_sha256(seed: dict[str, Any]) -> str:
    encoded = json.dumps(
        seed, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _current_source_snapshot() -> dict[str, str]:
    paths = [ROOT / relative for relative in INLINE_MODULES]
    paths.append(ROOT / "src/starnet/submission/config.json")
    paths.extend(sorted((ROOT / "src/starnet/submission/prompt").glob("*.txt")))
    return {str(path.relative_to(ROOT)): _sha256_path(path) for path in paths}


def _action_payload(action: Action | None) -> dict[str, Any] | None:
    if action is None:
        return None
    return {
        "kind": action.kind,
        "target_node_1": action.target_node_1,
        "target_node_2": action.target_node_2,
        "prompt_id": action.prompt_id,
    }


class LoggedEnvironment(CurrentRulesEnvironment):
    """Record public action results and resource movement without exposing r."""

    def __init__(self, seed: dict[str, Any]) -> None:
        super().__init__(seed)
        self.action_log: list[dict[str, Any]] = []

    def _append(
        self, kind: str, before: float, after: float, success: bool,
        result: object, **targets: object,
    ) -> None:
        self.action_log.append({
            "index": len(self.action_log) + 1,
            "kind": kind,
            **targets,
            "budget_before": before,
            "budget_after": after,
            "success": success,
            "public_result": result,
        })

    def scan_node(self, node_id: int):
        before = self.get_remaining_budget()
        result = super().scan_node(node_id)
        self._append(
            "scan", before, self.get_remaining_budget(), result is not None, result,
            target_node_1=node_id, target_node_2=None, prompt_id=None,
        )
        return result

    def communicate(self, node_id: int, prompt_id: int):
        before = self.get_remaining_budget()
        result = super().communicate(node_id, prompt_id)
        success = isinstance(result, dict) and result.get("status") == "success"
        self._append(
            "comm", before, self.get_remaining_budget(), success, result,
            target_node_1=node_id, target_node_2=None, prompt_id=prompt_id,
        )
        return result

    def cut_link(self, left: int, right: int):
        before = self.get_remaining_budget()
        result = super().cut_link(left, right)
        self._append(
            "cut", before, self.get_remaining_budget(), result is True, result,
            target_node_1=left, target_node_2=right, prompt_id=None,
        )
        return result

    def shield_node(self, node_id: int):
        before = self.get_remaining_budget()
        result = super().shield_node(node_id)
        self._append(
            "shield", before, self.get_remaining_budget(), result is True, result,
            target_node_1=node_id, target_node_2=None, prompt_id=None,
        )
        return result


def _arm_result(env: LoggedEnvironment, started: float, **extra: object) -> dict[str, Any]:
    action_counts = {
        kind: sum(item["kind"] == kind for item in env.action_log)
        for kind in ("scan", "comm", "cut", "shield")
    }
    action_log_sha256 = _sha256_bytes(json.dumps(
        env.action_log, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    return {
        "score": env.evaluate(),
        "remaining_budget": env.get_remaining_budget(),
        "action_counts": action_counts,
        "action_attempts": len(env.action_log),
        "action_failures": sum(not item["success"] for item in env.action_log),
        "action_log_sha256": action_log_sha256,
        "action_log": env.action_log,
        "elapsed_seconds": time.perf_counter() - started,
        **extra,
    }


def _run_archive(seed: dict[str, Any], arm: str, archive: Path) -> dict[str, Any]:
    started = time.perf_counter()
    env = LoggedEnvironment(seed)
    llm = CountingLLM(timeout=1.0, offline_only=True)
    previous_cwd = Path.cwd()
    with TemporaryDirectory(prefix=f"p9-{arm}-") as directory:
        folder = Path(directory)
        config = extract_submission(archive, folder)
        try:
            os.chdir(folder)
            module_name = f"p9_archive_{arm}_{os.getpid()}"
            spec = importlib.util.spec_from_file_location(module_name, folder / "starnet_model.py")
            if spec is None or spec.loader is None:
                raise RuntimeError("archive entry module cannot be loaded")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            model = module.ParticipantSquadModel(env, config["person"], llm)
            for model_calls in range(1, 121):
                status = model.step()
                if status or env.get_remaining_budget() < 0.5:
                    break
            controller = model.controller
            return _arm_result(
                env,
                started,
                execution_mode=(
                    "archive_casevo_forced_llm_exception_fallback"
                    if llm.blocked_calls else "archive_casevo_llm_off"
                ),
                archive=archive.name,
                archive_sha256=_sha256_path(archive),
                model_sha256=_sha256_path(folder / "starnet_model.py"),
                controller_type=type(controller).__name__,
                effective_p8_mode=getattr(controller, "p8_mode", None),
                model_calls=model_calls,
                stop_reason=str(controller.stop_reason),
                llm_attempts=llm.attempts,
                llm_forced_failures=llm.blocked_calls,
                llm_transport_errors=llm.errors,
                llm_accepted=getattr(controller, "llm_accepted", None),
                llm_fallbacks=getattr(controller, "llm_fallbacks", None),
                p8_proposals=getattr(controller, "p8_proposals", None),
                p8_planning_errors=getattr(controller, "p8_planning_errors", None),
            )
        finally:
            os.chdir(previous_cwd)


def _run_current_source(seed: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    env = LoggedEnvironment(seed)
    llm = CountingLLM(timeout=1.0, offline_only=True)
    config_path = ROOT / "src/starnet/submission/config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    model = CurrentParticipantSquadModel(env, config["person"], llm)
    for model_calls in range(1, 121):
        status = model.step()
        if status or env.get_remaining_budget() < 0.5:
            break
    controller = model.controller
    return _arm_result(
        env,
        started,
        execution_mode="current_source_casevo_forced_llm_exception_fallback",
        source_snapshot=_current_source_snapshot(),
        controller_type=type(controller).__name__,
        effective_p8_mode=getattr(controller, "p8_mode", None),
        model_calls=model_calls,
        stop_reason=str(controller.stop_reason),
        llm_attempts=llm.attempts,
        llm_forced_failures=llm.blocked_calls,
        llm_transport_errors=llm.errors,
        llm_accepted=getattr(controller, "llm_accepted", None),
        llm_fallbacks=getattr(controller, "llm_fallbacks", None),
        p8_proposals=getattr(controller, "p8_proposals", None),
        p8_planning_errors=getattr(controller, "p8_planning_errors", None),
        p8_refresh_reasons=getattr(controller, "p8_refresh_reasons", None),
        p8_selected_proposals=getattr(controller, "p8_selected_proposals", None),
        p8_selected_baseline=getattr(controller, "p8_selected_baseline", None),
    )


def _run_coverage(seed: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    env = LoggedEnvironment(seed)
    board = Blackboard(node_count=len(seed["nodes"]))
    observed: dict[int, float] = {}
    decisions: list[dict[str, Any]] = []
    planning_calls = rollouts = 0
    action_limit = 117
    for node_id in range(1, len(seed["nodes"]) + 1):
        action = Action("scan", node_id)
        budget = env.get_remaining_budget()
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal coverage13 scan")
        if not apply_action_outcome(env, board, action, budget).succeeded:
            raise RuntimeError("coverage13 scan failed")
    salt = public_board_salt(board)
    while len(env.action_log) < action_limit:
        budget = env.get_remaining_budget()
        decision = choose_coverage_action(
            board,
            budget,
            observed,
            remaining_steps=action_limit - len(env.action_log),
            salt=salt,
        )
        planning_calls += 1
        rollouts += decision.rollouts
        action = decision.action
        decisions.append({
            "action_index": len(env.action_log) + 1,
            "action": _action_payload(action),
            "baseline_action": _action_payload(decision.baseline_action),
            "proposed_action": _action_payload(decision.proposed_action),
            "source": decision.source,
            "deviated": decision.deviated,
            "mean_delta": decision.mean_delta,
            "minimum_delta": decision.minimum_delta,
            "audit_mean_delta": decision.audit_mean_delta,
            "audit_minimum_delta": decision.audit_minimum_delta,
            "compared_actions": [_action_payload(item) for item in decision.compared_actions],
        })
        if action is None:
            break
        if not is_legal_action(action, board, budget):
            raise RuntimeError("illegal coverage13 planned action")
        old_w = board.nodes[action.target_node_1].w if action.kind == "comm" else None
        turn = 4 - board.nodes[action.target_node_1].comm_left if action.kind == "comm" else None
        outcome = apply_action_outcome(env, board, action, budget)
        if not outcome.succeeded:
            break
        if action.kind == "comm" and turn == 1:
            if old_w is None:
                raise RuntimeError("missing pre-communication public value")
            observed[action.target_node_1] = board.nodes[action.target_node_1].w - old_w
    return _arm_result(
        env,
        started,
        execution_mode="pure_policy_no_llm_development_only",
        policy="coverage13",
        policy_sha256=_sha256_path(ROOT / "src/starnet/policy/p9_coverage_experiment.py"),
        p8_policy_sha256=_sha256_path(ROOT / "src/starnet/policy/p8_experiment.py"),
        public_board_salt=salt,
        planning_calls=planning_calls,
        rollouts=rollouts,
        decisions=decisions,
        deviation_count=sum(item["deviated"] for item in decisions),
        stop_reason=("no_candidate" if decisions and decisions[-1]["action"] is None else "resource_limit"),
        llm_attempts=0,
    )


def _interventions(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in result["action_log"] if item["kind"] != "scan"]


def _first_divergence(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    left_actions, right_actions = _interventions(left), _interventions(right)
    width = max(len(left_actions), len(right_actions))
    keys = ("kind", "target_node_1", "target_node_2", "prompt_id")
    for index in range(width):
        first = left_actions[index] if index < len(left_actions) else None
        second = right_actions[index] if index < len(right_actions) else None
        first_key = tuple(first[key] for key in keys) if first else None
        second_key = tuple(second[key] for key in keys) if second else None
        if first_key != second_key:
            return {
                "intervention_index": index + 1,
                "left": first,
                "right": second,
            }
    return None


def _run_case(job: tuple[str, int, str, tuple[str, ...], dict[str, str], bool]) -> dict[str, Any]:
    family, repetition, shift, selected_arms, source_snapshot, confirmation = job
    if CURRENT_ARM in selected_arms and _current_source_snapshot() != source_snapshot:
        raise RuntimeError("current source changed after the experiment was configured")
    seed = seed_payload(family, repetition, shift, allow_confirmation=confirmation)
    arms = {}
    if CURRENT_ARM in selected_arms:
        arms[CURRENT_ARM] = _run_current_source(seed)
    for arm, archive in ARCHIVES.items():
        if arm in selected_arms:
            arms[arm] = _run_archive(seed, arm, ROOT / "artifacts/submission" / archive)
    if COVERAGE_ARM in selected_arms:
        arms[COVERAGE_ARM] = _run_coverage(seed)
    if CURRENT_ARM in selected_arms and _current_source_snapshot() != source_snapshot:
        raise RuntimeError("current source changed while the case was running")
    comparisons = (
        (CURRENT_ARM, "official_best_experimental"),
        (CURRENT_ARM, "p8_submitted"),
        ("p8_submitted", "official_best_experimental"),
        (COVERAGE_ARM, "official_best_experimental"),
        (COVERAGE_ARM, "p8_submitted"),
        (COVERAGE_ARM, CURRENT_ARM),
    )
    paired_deltas = {}
    first_divergence = {}
    for left, right in comparisons:
        if left in arms and right in arms:
            name = f"{left}_vs_{right}"
            paired_deltas[name] = arms[left]["score"] - arms[right]["score"]
            first_divergence[name] = _first_divergence(arms[left], arms[right])
    return {
        "family": family,
        "repetition": repetition,
        "shift_stratum": shift,
        "seed_sha256": _seed_sha256(seed),
        "arms": arms,
        "paired_scores": {arm: result["score"] for arm, result in arms.items()},
        "paired_deltas": paired_deltas,
        "first_divergence": first_divergence,
    }


def _summarize(
    rows: list[dict[str, Any]], repetitions: tuple[int, ...],
) -> dict[str, Any]:
    delta_names = tuple(sorted({
        name for row in rows for name in row["paired_deltas"]
    }))

    def group(selected: list[dict[str, Any]]) -> dict[str, Any]:
        result = {"cases": len(selected)}
        if not selected:
            return result
        for name in delta_names:
            values = [row["paired_deltas"][name] for row in selected]
            result[name] = {
                "mean": statistics.fmean(values),
                "minimum": min(values),
                "maximum": max(values),
                "win_tie_loss": [
                    sum(value > 1e-8 for value in values),
                    sum(abs(value) <= 1e-8 for value in values),
                    sum(value < -1e-8 for value in values),
                ],
            }
        return result

    return {
        "overall": group(rows),
        "by_repetition": {
            str(repetition): group([row for row in rows if row["repetition"] == repetition])
            for repetition in repetitions
        },
        "by_shift": {
            shift: group([row for row in rows if row["shift_stratum"] == shift])
            for shift in SHIFT_STRATA
        },
        "by_family": {
            family: group([row for row in rows if row["family"] == family])
            for family in FAMILIES
        },
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validate_mechanism_gate() -> str:
    if not MECHANISM_REPORT.is_file():
        raise RuntimeError("missing public response-bound mechanism report")
    report = json.loads(MECHANISM_REPORT.read_text(encoding="utf-8"))
    observations = [
        observation
        for run in report.get("runs", [])
        for observation in run.get("observations", [])
    ]
    if (
        not observations
        or any(abs(float(item.get("bounded_error", float("inf")))) > 1e-9
               for item in observations)
        or not any(abs(float(item.get("unbounded_error", 0.0))) > 1e-9
                   for item in observations)
    ):
        raise RuntimeError("public mechanism report does not establish per-action [-100,100] clipping")
    return _sha256_path(MECHANISM_REPORT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", nargs="+", type=int, required=True)
    parser.add_argument("--shifts", nargs="+", choices=SHIFT_STRATA, default=list(SHIFT_STRATA))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--arms", nargs="+",
        choices=(CURRENT_ARM, "official_best_experimental", "p8_submitted", COVERAGE_ARM),
        default=[CURRENT_ARM, "official_best_experimental", "p8_submitted"],
    )
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "experiments/reports/p9-distribution-development-20260913.json",
    )
    args = parser.parse_args()
    repetitions = tuple(dict.fromkeys(args.repetitions))
    shifts = tuple(dict.fromkeys(args.shifts))
    selected_arms = tuple(dict.fromkeys(args.arms))
    allowed_repetitions = (
        CONFIRMATION_REPETITIONS[:3] if args.confirm else DEVELOPMENT_REPETITIONS
    )
    if not repetitions or not set(repetitions).issubset(allowed_repetitions):
        parser.error(
            "use development repetitions 901-902, or --confirm with frozen 1001-1003"
        )
    if args.workers not in (1, 2):
        parser.error("workers must be 1 or 2")
    for archive in ARCHIVES.values():
        if not (ROOT / "artifacts/submission" / archive).is_file():
            parser.error(f"missing archive: {archive}")
    mechanism_report_sha256 = _validate_mechanism_gate()

    source_snapshot = _current_source_snapshot() if CURRENT_ARM in selected_arms else {}
    config = {
        "schema_version": 1,
        "cohort": "bounded_confirmation" if args.confirm else "development",
        "declared_repetitions": list(allowed_repetitions),
        "families": list(FAMILIES),
        "shift_strata": list(SHIFT_STRATA),
        "arms": list(selected_arms),
        "execution_modes": {
            "official_best_experimental": "unchanged archive; LLM disabled by archive",
            "p8_submitted": "unchanged archive; forced LLM exception and deterministic fallback",
            CURRENT_ARM: "current source; forced LLM exception and deterministic fallback",
            **({COVERAGE_ARM: "pure policy; no LLM; development only"}
               if COVERAGE_ARM in selected_arms else {}),
        },
        "archive_sha256": {
            arm: _sha256_path(ROOT / "artifacts/submission" / archive)
            for arm, archive in ARCHIVES.items()
        },
        "coverage_policy_sha256": (
            _sha256_path(ROOT / "src/starnet/policy/p9_coverage_experiment.py")
            if COVERAGE_ARM in selected_arms else None
        ),
        "current_source_snapshot": source_snapshot,
        "seed_generator_sha256": _sha256_path(
            ROOT / "src/starnet/experiments/p9_distribution_seeds.py"
        ),
        "simulation_runner_sha256": _sha256_path(
            ROOT / "scripts/run_local_policy_matrix.py"
        ),
        "experiment_runner_sha256": _sha256_path(Path(__file__)),
        "mechanism_gate": {
            "communication_update": "clip(previous_w + response, -100, 100) after each success",
            "public_probe_report": str(MECHANISM_REPORT.relative_to(ROOT)),
            "public_probe_sha256": mechanism_report_sha256,
        },
        "confirmation_opened": args.confirm,
        "unused_reserved_repetitions": list(CONFIRMATION_REPETITIONS[3:]),
    }
    progress_path = args.output.with_suffix(".progress.json")
    rows: list[dict[str, Any]] = []
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("config") != config:
            parser.error("existing progress was produced by a different source/configuration")
        rows = list(progress.get("rows", []))
    completed = {
        (row["family"], row["repetition"], row["shift_stratum"])
        for row in rows
    }
    jobs = [
        (family, repetition, shift, selected_arms, source_snapshot, args.confirm)
        for repetition in repetitions
        for family in FAMILIES
        for shift in shifts
        if (family, repetition, shift) not in completed
    ]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run_case, job): job for job in jobs}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            rows.sort(key=lambda item: (
                item["repetition"], FAMILIES.index(item["family"]),
                SHIFT_STRATA.index(item["shift_stratum"]),
            ))
            _write_json(progress_path, {"config": config, "rows": rows})
            print(json.dumps({
                "family": row["family"],
                "repetition": row["repetition"],
                "shift_stratum": row["shift_stratum"],
                "paired_scores": row["paired_scores"],
                "paired_deltas": row["paired_deltas"],
                "completed_cases": len(rows),
            }, ensure_ascii=False), flush=True)

    expected = len(FAMILIES) * len(SHIFT_STRATA) * len(allowed_repetitions)
    report = {
        "config": config,
        "complete": len(rows) == expected,
        "completed_cases": len(rows),
        "expected_cases": expected,
        "summary": _summarize(rows, allowed_repetitions),
        "rows": rows,
        "platform_score": None,
        "production_promotion_allowed": False,
    }
    if CURRENT_ARM in selected_arms and _current_source_snapshot() != source_snapshot:
        raise RuntimeError("current source changed before final report generation")
    _write_json(args.output, report)
    print(json.dumps({
        "complete": report["complete"],
        "completed_cases": len(rows),
        "summary": report["summary"]["overall"],
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

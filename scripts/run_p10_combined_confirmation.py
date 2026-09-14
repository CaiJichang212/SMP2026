#!/usr/bin/env python3
"""Run a frozen P10 runtime candidate on the closed 48-case confirmation cohort."""

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.build_submission import INLINE_MODULES
from scripts.compare_submission_archives import CountingLLM, extract_submission
from scripts.run_p10_casevo_trial import P10TrialModel
from scripts.run_p10_runtime_arm_comparison import rank_terminal_then_first
from scripts.run_p9_distribution_validation import LoggedEnvironment
from starnet.experiments.p10_confirmation_seeds import (
    CONFIRMATION_REPETITIONS, FAMILIES, STRATA, seed_payload,
)


PROTOCOL = ROOT / "experiments/manifests/p10-combined-validation-20260914.json"
ARCHIVES = {
    "p9_archive": "starnet-p9-bounded-response-20260913.zip",
    "official_best_archive": "starnet-public-greedy-experimental-20260908.zip",
}
EXPERIMENT_MODULES = (
    "src/starnet/experiments/p9_distribution_seeds.py",
    "src/starnet/policy/public_response_mixture.py",
    "src/starnet/policy/p10_structure_plan_experiment.py",
    "src/starnet/runtime/p10_controller_experiment.py",
    "scripts/run_p10_casevo_trial.py",
    "scripts/run_p10_runtime_arm_comparison.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_snapshot() -> dict[str, str]:
    paths = [ROOT / relative for relative in (*INLINE_MODULES, *EXPERIMENT_MODULES)]
    paths.append(ROOT / "src/starnet/submission/config.json")
    paths.extend(sorted((ROOT / "src/starnet/submission/prompt").glob("*.txt")))
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def terminal_gain_ranker(payload, decisions=None):
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("mock ranker requires validated candidates")
    if any(any(key not in item for key in ("candidate_id", "evidence_ids", "score", "reason"))
           or not item["evidence_ids"] for item in candidates):
        raise ValueError("candidate payload is incomplete")
    decision = rank_terminal_then_first(payload)
    if decisions is not None:
        decisions.append({"candidate_ids": [candidate["candidate_id"] for candidate in candidates],
                          "candidate_scores": {candidate["candidate_id"]: candidate["score"]
                                               for candidate in candidates},
                          "selected_candidate_id": decision["candidate_id"],
                          "state_version": payload["state_version"]})
    return decision


def _run_model(model, env: LoggedEnvironment, decisions: list[dict]) -> dict:
    controller = model.controller
    controller.commander.llm_ranker = lambda payload: terminal_gain_ranker(payload, decisions)
    started = time.perf_counter()
    for host_calls in range(1, 121):
        before = len(env.action_log)
        status = model.step()
        if len(env.action_log) - before > 1:
            raise RuntimeError("one host step issued multiple public actions")
        if status or controller.stopped or env.get_remaining_budget() < 0.5:
            break
    if not controller.stopped and host_calls >= 120:
        raise RuntimeError("host call cap reached without controller stop")
    return {
        "score": env.evaluate(),
        "remaining_budget": env.get_remaining_budget(),
        "host_calls": host_calls,
        "action_attempts": len(env.action_log),
        "action_failures": controller.action_failures,
        "action_log_sha256": json_digest(env.action_log),
        "action_log": env.action_log,
        "model_decisions": decisions,
        "llm_calls": controller.llm_calls,
        "llm_accepted": controller.llm_accepted,
        "llm_fallbacks": controller.llm_fallbacks,
        "p8_planning_errors": getattr(controller, "p8_planning_errors", 0),
        "p10_planning_errors": getattr(controller, "p10_planning_errors", 0),
        "p10_approved_plans": getattr(controller, "p10_approved_plans", 0),
        "p10_prefix_completed": getattr(controller, "p10_prefix_completed", 0),
        "p10_prefix_failures": getattr(controller, "p10_prefix_failures", 0),
        "p10_response_switches": getattr(controller, "p10_response_switches", 0),
        "p10_response_disabled": getattr(controller, "p10_response_disabled", False),
        "p10_response_disable_reason": getattr(controller, "p10_response_disable_reason", None),
        "p10_response_activation": getattr(
            getattr(controller, "p10_response_estimator", None), "activation", None,
        ),
        "elapsed_seconds": time.perf_counter() - started,
    }


def run_candidate(seed: dict, variant: str) -> dict:
    env = LoggedEnvironment(seed)
    llm = CountingLLM(1.0, offline_only=True)
    people = json.loads((ROOT / "src/starnet/submission/config.json").read_text())["person"]
    model = P10TrialModel(env, people, llm, experiment_mode=variant)
    decisions: list[dict] = []
    result = _run_model(model, env, decisions)
    result.update({"execution": "current P10 CaseVO controller with valid first-candidate mock",
                   "variant": variant, "source_snapshot": source_snapshot()})
    return result


def run_archive(seed: dict, arm: str, archive: Path) -> dict:
    env = LoggedEnvironment(seed)
    llm = CountingLLM(1.0, offline_only=True)
    previous_cwd = Path.cwd()
    with TemporaryDirectory(prefix=f"p10-confirm-{arm}-") as directory:
        folder = Path(directory)
        config = extract_submission(archive, folder)
        try:
            os.chdir(folder)
            module_name = f"p10_confirm_{arm}_{os.getpid()}"
            spec = importlib.util.spec_from_file_location(module_name, folder / "starnet_model.py")
            if spec is None or spec.loader is None:
                raise RuntimeError("archive entry cannot be imported")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            model = module.ParticipantSquadModel(env, config["person"], llm)
            decisions: list[dict] = []
            result = _run_model(model, env, decisions)
            result.update({"execution": "unchanged archive with valid first-candidate mock",
                           "archive": archive.name, "archive_sha256": digest(archive),
                           "model_sha256": digest(folder / "starnet_model.py")})
            return result
        finally:
            os.chdir(previous_cwd)


def first_divergence(candidate: dict, control: dict):
    left, right = candidate["action_log"], control["action_log"]
    for index in range(max(len(left), len(right))):
        first = left[index] if index < len(left) else None
        second = right[index] if index < len(right) else None
        keys = ("kind", "target_node_1", "target_node_2", "prompt_id")
        if ((tuple(first.get(key) for key in keys) if first else None)
                != (tuple(second.get(key) for key in keys) if second else None)):
            return {"action_index": index + 1, "candidate": first, "control": second}
    return None


def run_case(job):
    family, repetition, stratum, variant, expected_snapshot = job
    if source_snapshot() != expected_snapshot:
        raise RuntimeError("candidate source changed before case execution")
    seed = seed_payload(family, repetition, stratum, allow_confirmation=True)
    candidate = run_candidate(seed, variant)
    arms = {"candidate": candidate}
    for arm, filename in ARCHIVES.items():
        arms[arm] = run_archive(seed, arm, ROOT / "artifacts/submission" / filename)
    if source_snapshot() != expected_snapshot:
        raise RuntimeError("candidate source changed during case execution")
    return {
        "family": family, "repetition": repetition, "stratum": stratum,
        "seed_sha256": json_digest(seed), "arms": arms,
        "paired_deltas": {
            "candidate_vs_p9": candidate["score"] - arms["p9_archive"]["score"],
            "candidate_vs_official_best": candidate["score"] - arms["official_best_archive"]["score"],
        },
        "first_divergence": {
            "candidate_vs_p9": first_divergence(candidate, arms["p9_archive"]),
            "candidate_vs_official_best": first_divergence(candidate, arms["official_best_archive"]),
        },
    }


def metric(rows, comparison):
    values = [row["paired_deltas"][comparison] for row in rows]
    return {"cases": len(values), "mean": statistics.fmean(values),
            "minimum": min(values), "maximum": max(values),
            "win_tie_loss": [sum(x > 1e-8 for x in values),
                             sum(abs(x) <= 1e-8 for x in values),
                             sum(x < -1e-8 for x in values)]}


def summarize(rows):
    def group(selected):
        return {name: metric(selected, name)
                for name in ("candidate_vs_p9", "candidate_vs_official_best")}
    return {
        "overall": group(rows),
        "by_stratum": {stratum: group([row for row in rows if row["stratum"] == stratum])
                       for stratum in STRATA},
        "by_family": {family: group([row for row in rows if row["family"] == family])
                      for family in FAMILIES},
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--variant", choices=("plan_only", "response_only", "combined"), required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.confirm:
        parser.error("confirmation is closed; pass --confirm only after winner/source freeze")
    snapshot = source_snapshot()
    config = {
        "protocol_sha256": digest(PROTOCOL), "runner_sha256": digest(Path(__file__)),
        "generator_sha256": digest(ROOT / "src/starnet/experiments/p10_confirmation_seeds.py"),
        "source_snapshot": snapshot, "selected_variant": args.variant,
        "families": list(FAMILIES), "strata": list(STRATA),
        "repetitions": list(CONFIRMATION_REPETITIONS),
        "archive_sha256": {arm: digest(ROOT / "artifacts/submission" / filename)
                           for arm, filename in ARCHIVES.items()},
        "ranker": "max terminal score for P10/P8/PG comparisons; list-first for ordinary P9",
    }
    progress = args.raw_output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        previous = json.loads(progress.read_text())
        if previous.get("config") != config:
            parser.error("confirmation progress identity mismatch")
        rows = list(previous["rows"])
    completed = {(row["family"], row["repetition"], row["stratum"]) for row in rows}
    jobs = [(family, repetition, stratum, args.variant, snapshot)
            for repetition in CONFIRMATION_REPETITIONS for family in FAMILIES for stratum in STRATA
            if (family, repetition, stratum) not in completed]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_case, job): job for job in jobs}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            rows.sort(key=lambda item: (item["repetition"], FAMILIES.index(item["family"]),
                                        STRATA.index(item["stratum"])))
            write_json(progress, {"config": config, "rows": rows})
            print(json.dumps({"family": row["family"], "repetition": row["repetition"],
                              "stratum": row["stratum"], "deltas": row["paired_deltas"],
                              "completed": len(rows)}, ensure_ascii=False), flush=True)
    raw = {"config": config, "complete": len(rows) == 48, "rows": rows}
    write_json(args.raw_output, raw)
    compact = {
        "config": config, "complete": raw["complete"], "summary": summarize(rows),
        "raw_log": {"path": str(args.raw_output.relative_to(ROOT)),
                    "sha256": digest(args.raw_output), "committed": False},
        "rows": [{"family": row["family"], "repetition": row["repetition"],
                  "stratum": row["stratum"], "seed_sha256": row["seed_sha256"],
                  "paired_deltas": row["paired_deltas"],
                  "first_divergence": row["first_divergence"],
                  "arms": {arm: {key: result.get(key) for key in (
                      "score", "remaining_budget", "host_calls", "action_attempts",
                      "action_failures", "action_log_sha256", "llm_calls", "llm_accepted",
                      "llm_fallbacks", "p8_planning_errors", "p10_planning_errors",
                      "p10_approved_plans", "p10_prefix_completed", "p10_prefix_failures",
                      "p10_response_switches", "p10_response_disabled",
                      "p10_response_disable_reason", "p10_response_activation")}
                           for arm, result in row["arms"].items()}}
                 for row in rows],
        "production_enabled": False, "platform_score": None,
    }
    write_json(args.output, compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

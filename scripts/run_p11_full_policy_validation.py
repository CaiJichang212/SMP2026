#!/usr/bin/env python3
"""Run full-cost P11 prompt learning against no-probe P9 references."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.build_submission import INLINE_MODULES
from scripts.compare_submission_archives import CountingLLM, extract_submission
from scripts.run_p9_distribution_validation import LoggedEnvironment
from starnet.experiments.p11_validation_seeds import confirmation_cases, development_cases
from starnet.policy.actions import Action, is_legal_action
from starnet.policy.config import PolicyMode
from starnet.policy.structural import ExperimentalPublicGreedyPlanner
from starnet.runtime.controller import RuntimeController
from starnet.runtime.p11_prompt_controller_experiment import PromptLearningRuntimeController
from starnet.runtime.stage import ContestStage
from starnet.submission.starnet_model import ParticipantSquadModel


PROTOCOL = ROOT / "experiments/manifests/p11-full-policy-validation-20260914.json"
P9_ARCHIVE = ROOT / "artifacts/submission/starnet-p9-bounded-response-20260913.zip"
EXPERIMENT_SOURCES = (
    "src/starnet/policy/prompt_calibration_experiment.py",
    "src/starnet/runtime/p11_prompt_controller_experiment.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_snapshot() -> dict[str, str]:
    paths = [ROOT / relative for relative in (*INLINE_MODULES, *EXPERIMENT_SOURCES)]
    paths.extend(sorted((ROOT / "src/starnet/submission/prompt").glob("*.txt")))
    paths.append(ROOT / "src/starnet/submission/config.json")
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def rank_first(payload, decisions):
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("valid first-candidate ranker requires candidates")
    item = candidates[0]
    decision = {"state_version": payload["state_version"], "mode": "single_action",
                "candidate_id": item["candidate_id"], "reason_code": "paired_first",
                "evidence_ids": [item["evidence_ids"][0]]}
    decisions.append({"candidate_ids": [candidate["candidate_id"] for candidate in candidates],
                      "selected_candidate_id": item["candidate_id"],
                      "selected_candidate": {key: item.get(key) for key in (
                          "candidate_id", "action", "score", "roi", "reason", "evidence_ids",
                      )},
                      "state_version": payload["state_version"]})
    return decision


class KnownPromptEnvironment(LoggedEnvironment):
    """Map P9's legal prompt-1 dispatch to a known best ID for diagnostics."""

    def __init__(self, seed, known_prompt_id):
        super().__init__(seed)
        self.known_prompt_id = known_prompt_id

    def communicate(self, node_id: int, prompt_id: int):
        dispatched = self.known_prompt_id if prompt_id == 1 else prompt_id
        result = super().communicate(node_id, dispatched)
        self.action_log[-1]["requested_prompt_id"] = prompt_id
        self.action_log[-1]["dispatched_prompt_id"] = dispatched
        return result


class OnlineMagnitudeController(RuntimeController):
    """Diagnostic fixed-ID planner using ordinary prompt-1 public magnitudes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.magnitude_observations = {}
        self.magnitude_censored = []

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        super()._refresh_candidates(budget, phase)
        if (self.effective_policy_mode is not PolicyMode.PUBLIC_GREEDY
                or len(self.blackboard.scanned_ids) != self.node_count
                or not self.magnitude_observations):
            return
        prior = statistics.fmean(float(value) for value in self.magnitude_observations.values())

        def response(node_id, _node, turn):
            first = self.magnitude_observations.get(node_id, prior)
            return float(first) * (0.5 ** (turn - 1))

        planner = ExperimentalPublicGreedyPlanner(
            response, candidate_limit=len(self.blackboard.edges) + 2 * len(self.blackboard.nodes) + 1,
            conservative_structure=True, min_observed_responses=0, structure_roi_margin=1.0,
            defer_comm_if_shieldable=self.config.enable_public_comm_shield_guard,
        )
        candidates = planner.candidates(
            self.blackboard, budget, self.failed_actions,
            observed_response_count=len(self.magnitude_observations),
        )
        self.candidates = {candidate.candidate_id: candidate for candidate in candidates}

    def _attempt_action(self, action: Action, candidate_id: str, budget: float) -> bool:
        node = self.blackboard.nodes.get(action.target_node_1)
        before = node.w if node is not None and action.kind == "comm" else None
        turn = (4 - int(node.comm_left or 0)
                if node is not None and action.kind == "comm" else None)
        success = super()._attempt_action(action, candidate_id, budget)
        if (not success or action.kind != "comm" or action.prompt_id != 1
                or action.target_node_1 in self.magnitude_observations
                or before is None or turn not in (1, 2, 3)):
            return success
        current = self.blackboard.nodes.get(action.target_node_1)
        if current is None:
            return success
        record = {"node_id": action.target_node_1, "turn": turn,
                  "before": before, "new_w": current.w}
        if before < -100.0 or before > 100.0 or abs(current.w) >= 100.0 - 1e-12:
            record["reason"] = "opinion_bound"
            self.magnitude_censored.append(record)
            return success
        normalized = (current.w - before) / (0.5 ** (turn - 1))
        if not isinstance(normalized, float) or not math.isfinite(normalized):
            record["reason"] = "nonfinite_response"
            self.magnitude_censored.append(record)
            return success
        self.magnitude_observations[action.target_node_1] = normalized
        return success


def run_model(model, env: LoggedEnvironment) -> dict:
    controller = model.controller
    decisions = []
    controller.commander.llm_ranker = lambda payload: rank_first(payload, decisions)
    host_deltas = []
    for host_calls in range(1, 121):
        before = len(env.action_log)
        decisions_before = len(decisions)
        status = model.step()
        host_deltas.append(len(env.action_log) - before)
        for decision in decisions[decisions_before:]:
            decision["selected_prompt_prior_after_step"] = getattr(
                controller, "p11_selected_prompt_prior", None,
            )
            decision["selected_prompt_id_after_step"] = getattr(
                controller, "p11_selected_prompt_id", None,
            )
        if host_deltas[-1] > 1:
            raise RuntimeError("multiple actions in one host step")
        if status or controller.stopped or env.get_remaining_budget() < 0.5:
            break
    ledger = getattr(controller, "p11_prompt_ledger", None)
    return {
        "score": env.evaluate(), "remaining_budget": env.get_remaining_budget(),
        "host_calls": host_calls, "host_action_deltas": host_deltas,
        "max_actions_per_host_step": max(host_deltas),
        "action_attempts": len(env.action_log),
        "action_failures": getattr(controller, "action_failures", 0),
        "action_log_sha256": json_digest(env.action_log), "action_log": env.action_log,
        "model_decisions": decisions, "llm_calls": getattr(controller, "llm_calls", 0),
        "llm_accepted": getattr(controller, "llm_accepted", None),
        "llm_fallbacks": getattr(controller, "llm_fallbacks", None),
        "controller_type": type(controller).__name__,
        "p8_planning_errors": getattr(controller, "p8_planning_errors", 0),
        "p11_probe_nodes": list(getattr(controller, "p11_probe_nodes", ())),
        "p11_probe_attempts": getattr(controller, "p11_probe_attempts", 0),
        "p11_probe_successes": getattr(controller, "p11_probe_successes", 0),
        "p11_probe_failures": getattr(controller, "p11_probe_failures", 0),
        "p11_probe_budget": getattr(controller, "p11_probe_budget", 0.0),
        "p11_calibration_finished": getattr(controller, "p11_calibration_finished", None),
        "p11_selected_prompt_id": getattr(controller, "p11_selected_prompt_id", None),
        "p11_selected_prompt_prior": getattr(controller, "p11_selected_prompt_prior", None),
        "p11_prompt_positive": getattr(controller, "p11_prompt_positive", None),
        "p11_fallback_to_p9": getattr(controller, "p11_fallback_to_p9", None),
        "p11_response_switches": getattr(controller, "p11_response_switches", 0),
        "p11_planning_errors": getattr(controller, "p11_planning_errors", 0),
        "p11_selected_prompt_dispatches": getattr(
            controller, "p11_selected_prompt_dispatches", 0,
        ),
        "p11_errors": getattr(controller, "p11_errors", 0),
        "p11_last_error": getattr(controller, "p11_last_error", None),
        "p11_selected_prompt_observations": getattr(
            controller, "p11_selected_prompt_observations", None,
        ),
        "p11_selected_response_censored": getattr(
            controller, "p11_selected_response_censored", None,
        ),
        "ledger": ({"accepted": ledger.accepted, "censored": ledger.censored,
                    "failures": ledger.failures, "confident": ledger.confident,
                    "calibration_complete": ledger.calibration_complete,
                    "provisional_prompt_ids": list(ledger.provisional_prompt_ids),
                    "calibrated_prompt_ids": list(ledger.calibrated_prompt_ids),
                    "normalized_values": ledger.normalized_values()}
                   if ledger is not None else None),
        "magnitude_observations": getattr(controller, "magnitude_observations", None),
        "magnitude_censored": getattr(controller, "magnitude_censored", None),
    }


def run_source(seed, mode: str) -> dict:
    env = LoggedEnvironment(seed)
    llm = CountingLLM(1.0, offline_only=True)
    people = json.loads((ROOT / "src/starnet/submission/config.json").read_text())["person"]
    model = ParticipantSquadModel(env, people, llm)
    if mode == "p11":
        model.controller = PromptLearningRuntimeController(
            env, llm_ranker=lambda payload: None, stage=ContestStage.PRELIMINARY,
            config=model.controller.config, p8_mode="conservative", require_stage_envelope=True,
        )
    elif mode == "fixed1_online_magnitude_no_probe":
        model.controller = OnlineMagnitudeController(
            env, llm_ranker=lambda payload: None, stage=ContestStage.PRELIMINARY,
            config=model.controller.config,
        )
    else:
        raise ValueError("unknown source arm")
    result = run_model(model, env)
    result["execution"] = mode
    return result


def run_archive(seed, known_prompt_id=None) -> dict:
    env = (KnownPromptEnvironment(seed, known_prompt_id)
           if known_prompt_id is not None else LoggedEnvironment(seed))
    llm = CountingLLM(1.0, offline_only=True)
    previous = Path.cwd()
    with TemporaryDirectory(prefix="p11-p9-") as directory:
        folder = Path(directory)
        config = extract_submission(P9_ARCHIVE, folder)
        try:
            os.chdir(folder)
            name = f"p11_p9_{os.getpid()}_{known_prompt_id or 0}"
            spec = importlib.util.spec_from_file_location(name, folder / "starnet_model.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            model = module.ParticipantSquadModel(env, config["person"], llm)
            result = run_model(model, env)
            result.update({"execution": "known_best_id_p9" if known_prompt_id else "p9_no_probe",
                           "archive_sha256": digest(P9_ARCHIVE),
                           "known_prompt_id": known_prompt_id})
            return result
        finally:
            os.chdir(previous)


def run_case(job):
    case_id, amplitude, values, seed, expected_snapshot = job
    if source_snapshot() != expected_snapshot:
        raise RuntimeError("P11 source changed before case")
    best = max(values)
    best_ids = tuple(index for index, value in enumerate(values, 1) if value == best)
    p11 = run_source(seed, "p11")
    p9 = run_archive(seed)
    known = run_archive(seed, known_prompt_id=best_ids[0])
    magnitude = run_source(seed, "fixed1_online_magnitude_no_probe")
    if source_snapshot() != expected_snapshot:
        raise RuntimeError("P11 source changed during case")
    parts = case_id.split(":")
    topology_block = (
        ":".join(parts[:2]) if parts[0] in {"er_resampled", "ba_resampled",
                                            "ws_resampled", "sbm_resampled"}
        else ":".join(parts[:3])
    )
    return {"case_id": case_id, "amplitude": amplitude,
            "topology_block": topology_block,
            "prompt_values": list(values), "best_prompt_ids": list(best_ids),
            "prompt1_best": 1 in best_ids, "seed_sha256": json_digest(seed),
            "arms": {"p11": p11, "p9_no_probe": p9,
                     "known_best_id_p9_reference": known,
                     "fixed1_online_magnitude_no_probe": magnitude},
            "paired": {"p11_vs_p9": p11["score"] - p9["score"],
                       "p11_signed_gap_to_known_id": known["score"] - p11["score"],
                       "p9_signed_gap_to_known_id": known["score"] - p9["score"],
                       "magnitude_vs_p9": magnitude["score"] - p9["score"]},
            "identified_best": p11["p11_selected_prompt_id"] in best_ids}


def metric(rows, key):
    values = [row["paired"][key] for row in rows]
    return {"cases": len(values), "mean": statistics.fmean(values),
            "minimum": min(values), "maximum": max(values),
            "win_tie_loss": [sum(x > 1e-8 for x in values),
                             sum(abs(x) <= 1e-8 for x in values),
                             sum(x < -1e-8 for x in values)]}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=("development", "confirmation"), default="development")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--checkpoint-every", type=int, default=5)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.cohort == "confirmation" and not args.confirm:
        parser.error("fresh P11 confirmation remains closed")
    if args.cohort == "development" and args.confirm:
        parser.error("--confirm is valid only for the frozen confirmation cohort")
    if args.checkpoint_every <= 0:
        parser.error("checkpoint interval must be positive")
    cases = (list(development_cases()) if args.cohort == "development"
             else list(confirmation_cases(allow_confirmation=True)))
    snapshot = source_snapshot()
    config = {"protocol_sha256": digest(PROTOCOL), "runner_sha256": digest(Path(__file__)),
              "seed_source_sha256": digest(ROOT / "src/starnet/experiments/p11_validation_seeds.py"),
              "ledger_sha256": digest(ROOT / "src/starnet/policy/prompt_calibration_experiment.py"),
              "source_snapshot": snapshot, "p9_archive_sha256": digest(P9_ARCHIVE),
              "cohort": args.cohort, "cases": len(cases), "workers": args.workers,
              "confirmation_opened": args.cohort == "confirmation"}
    progress = args.raw_output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("P11 progress identity mismatch")
        rows = list(saved["rows"])
    completed = {row["case_id"] for row in rows}
    jobs = [(case_id, amplitude, values, seed, snapshot)
            for case_id, amplitude, values, seed in cases if case_id not in completed]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        iterator = iter(jobs)
        futures = {}
        for _ in range(args.workers):
            job = next(iterator, None)
            if job is not None:
                futures[pool.submit(run_case, job)] = job[0]
        try:
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    case_id = futures.pop(future)
                    row = future.result()
                    rows.append(row)
                    if len(rows) % args.checkpoint_every == 0:
                        write_json(progress, {"config": config, "rows": rows})
                    print(json.dumps({"case_id": row["case_id"], "completed": len(rows),
                                      "p11_vs_p9": row["paired"]["p11_vs_p9"],
                                      "probe_budget": row["arms"]["p11"]["p11_probe_budget"]},
                                     ensure_ascii=False), flush=True)
                    job = next(iterator, None)
                    if job is not None:
                        futures[pool.submit(run_case, job)] = job[0]
        except Exception as exc:
            for pending in futures:
                pending.cancel()
            write_json(progress, {"config": config, "rows": rows,
                                  "error": {"case_id": case_id,
                                            "type": type(exc).__name__}})
            raise
    write_json(progress, {"config": config, "rows": rows})
    raw = {"config": config, "complete": len(rows) == len(cases), "rows": rows}
    write_json(args.raw_output, raw)
    compact = {"config": config, "complete": raw["complete"],
               "summary": {key: metric(rows, key) for key in (
                   "p11_vs_p9", "p11_signed_gap_to_known_id",
                   "p9_signed_gap_to_known_id", "magnitude_vs_p9")},
               "raw_log": {"path": str(args.raw_output.resolve().relative_to(ROOT)),
                           "sha256": digest(args.raw_output), "committed": False},
               "rows": [{"case_id": row["case_id"], "amplitude": row["amplitude"],
                          "prompt_values": row["prompt_values"],
                          "best_prompt_ids": row["best_prompt_ids"],
                          "prompt1_best": row["prompt1_best"], "paired": row["paired"],
                          "identified_best": row["identified_best"],
                          "seed_sha256": row["seed_sha256"],
                          "arms": {arm: {"score": value["score"],
                                         "remaining_budget": value["remaining_budget"],
                                         "action_attempts": value["action_attempts"],
                                         "action_failures": value["action_failures"],
                                          "action_log_sha256": value["action_log_sha256"],
                                          "p11_probe_budget": value["p11_probe_budget"],
                                         "p11_selected_prompt_id": value["p11_selected_prompt_id"],
                                         "p11_selected_prompt_prior": value["p11_selected_prompt_prior"],
                                         "p11_selected_prompt_dispatches": value["p11_selected_prompt_dispatches"],
                                         "p11_planning_errors": value["p11_planning_errors"]}
                                   for arm, value in row["arms"].items()}}
                         for row in rows], "production_enabled": False,
               "platform_score": None}
    write_json(args.output, compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

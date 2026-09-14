#!/usr/bin/env python3
"""CaseVO/LLM development trial for the isolated P10 prefix controller."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_submission_archives import CountingLLM
from scripts.run_baseline_openai import load_local_env
from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p10_structure_plan_search import run_policy
from starnet.experiments.p8_seeds import DEVELOPMENT_REPETITIONS, FAMILIES, seed_payload
from starnet.runtime.p10_controller_experiment import P10RuntimeController
from starnet.runtime.stage import ContestStage
from starnet.submission.starnet_model import ParticipantSquadModel


class P10TrialModel(ParticipantSquadModel):
    def __init__(self, host_env, person_list, llm, *, experiment_mode="plan_only"):
        super().__init__(host_env, person_list, llm)
        self.controller = P10RuntimeController(
            host_env,
            llm_ranker=self.commander_agent.rank_candidates,
            stage=ContestStage.PRELIMINARY,
            config=self.controller.config,
            p8_mode="conservative",
            max_structures=12,
            beam_width=4,
            experiment_mode=experiment_mode,
        )


def run_trial(seed, *, llm_mode="mock-plan", timeout=20, experiment_mode="plan_only"):
    real = llm_mode == "real"
    llm = CountingLLM(timeout, offline_only=not real)
    env = LocalPublicEnvironment(seed)
    people = json.loads((ROOT / "src/starnet/submission/config.json").read_text())["person"]
    model = P10TrialModel(env, people, llm, experiment_mode=experiment_mode)
    payloads = []
    if llm_mode in {"mock-plan", "mock-baseline"}:
        def rank(payload):
            payloads.append(payload)
            candidates = payload["candidates"]
            if any(item["candidate_id"].startswith("p10-plan:") for item in candidates):
                wanted = "p10-plan:" if llm_mode == "mock-plan" else None
                item = next(
                    candidate for candidate in candidates
                    if candidate["candidate_id"].startswith(wanted) if wanted is not None
                ) if wanted is not None else next(
                    candidate for candidate in candidates
                    if not candidate["candidate_id"].startswith("p10-plan:")
                )
            else:
                item = candidates[0]
            return {
                "state_version": payload["state_version"], "mode": "single_action",
                "candidate_id": item["candidate_id"], "reason_code": "p10_trial",
                "evidence_ids": [item["evidence_ids"][0]],
            }
        model.controller.commander.llm_ranker = rank
    while not model.controller.stopped:
        before = len(env.calls)
        model.step()
        if len(env.calls) - before > 1:
            raise RuntimeError("P10 host step issued more than one public action")
        if model.controller.step_number > 119:
            raise RuntimeError("P10 trial step limit exceeded")
        if real and llm.errors >= 3:
            raise RuntimeError("three real LLM transport failures")
    controller = model.controller
    return {
        "score": env.evaluate(),
        "actions": {kind: sum(call[0] == kind for call in env.calls)
                    for kind in ("scan", "comm", "cut", "shield")},
        "remaining_budget": env.get_remaining_budget(),
        "llm_mode": llm_mode,
        "llm_model": llm.chat.model if real else None,
        "llm_calls": controller.llm_calls,
        "llm_accepted": controller.llm_accepted,
        "llm_fallbacks": controller.llm_fallbacks,
        "transport_errors": llm.errors,
        "action_failures": controller.action_failures,
        "p8_planning_errors": controller.p8_planning_errors,
        "p10_searches": controller.p10_searches,
        "p10_planning_errors": controller.p10_planning_errors,
        "p10_approved_plans": controller.p10_approved_plans,
        "p10_baseline_choices": controller.p10_baseline_choices,
        "p10_prefix_successes": controller.p10_prefix_successes,
        "p10_prefix_failures": controller.p10_prefix_failures,
        "p10_prefix_completed": controller.p10_prefix_completed,
        "p10_experiment_mode": controller.p10_experiment_mode,
        "p10_response_switches": controller.p10_response_switches,
        "p10_response_disabled": controller.p10_response_disabled,
        "p10_response_disable_reason": controller.p10_response_disable_reason,
        "p10_response_gate_open": (
            controller.p10_response_estimator.gate_open()
            if controller.p10_response_estimator is not None
            and not controller.p10_response_disabled else False
        ),
        "p10_response_activation": getattr(
            controller.p10_response_estimator, "activation", None,
        ),
        "action_attempts": controller.action_attempts,
        "payloads": payloads,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=FAMILIES, default="ba_negative_hubs")
    parser.add_argument("--repetition", type=int, choices=DEVELOPMENT_REPETITIONS, default=501)
    parser.add_argument("--llm-mode", choices=("real", "mock-plan", "mock-baseline", "unavailable"),
                        default="mock-plan")
    parser.add_argument("--experiment-mode", choices=(
        "plan_only", "response_only", "combined", "guarded_combined",
    ),
                        default="plan_only")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.llm_mode == "real":
        load_local_env(ROOT / ".env")
    seed = seed_payload(args.family, args.repetition)
    baseline = run_policy(seed, None)
    candidate = run_trial(seed, llm_mode=args.llm_mode,
                          experiment_mode=args.experiment_mode)
    report = {
        "family": args.family, "repetition": args.repetition,
        "baseline": baseline, "candidate": candidate,
        "delta": candidate["score"] - baseline["score"],
        "evaluation": "local CaseVO orchestration development trial",
        "confirmation_opened": False, "production_enabled": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "family": args.family, "delta": report["delta"],
        "p10_approved_plans": candidate["p10_approved_plans"],
        "p10_prefix_completed": candidate["p10_prefix_completed"],
        "action_failures": candidate["action_failures"],
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

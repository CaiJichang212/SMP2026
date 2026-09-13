#!/usr/bin/env python3
"""CaseVO/LLM research trial for the frozen P8 policy; not a submission flag."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_submission_archives import CountingLLM
from scripts.run_baseline_openai import load_local_env
from scripts.run_local_policy_matrix import LocalPublicEnvironment, run_variant
from starnet.experiments.p8_seeds import DEVELOPMENT_REPETITIONS, FAMILIES, seed_payload
from starnet.runtime.stage import ContestStage
from starnet.submission.starnet_model import ParticipantSquadModel


from starnet.runtime.p8_controller import P8RuntimeController as P8TrialController


class P8TrialModel(ParticipantSquadModel):
    def __init__(self, host_env, person_list, llm, *, p8_mode="audited"):
        super().__init__(host_env, person_list, llm)
        self.controller = P8TrialController(
            host_env, llm_ranker=self.commander_agent.rank_candidates,
            stage=ContestStage.PRELIMINARY, config=self.controller.config, p8_mode=p8_mode,
        )


def run_trial(seed, *, llm_mode="mock", timeout=20, p8_mode="audited"):
    llm = CountingLLM(timeout, offline_only=llm_mode != "real")
    env = LocalPublicEnvironment(seed)
    people = json.loads((ROOT / "src/starnet/submission/config.json").read_text())["person"]
    model = P8TrialModel(env, people, llm, p8_mode=p8_mode)
    if llm_mode == "mock":
        def rank(payload):
            item = payload["candidates"][0]
            return {"state_version": payload["state_version"], "mode": "single_action",
                    "candidate_id": item["candidate_id"], "reason_code": "mock_top_candidate",
                    "evidence_ids": [item["evidence_ids"][0]]}
        model.controller.commander.llm_ranker = rank
    while not model.controller.stopped:
        model.step()
        if model.controller.step_number > 119:
            raise RuntimeError("trial step limit exceeded")
        if llm_mode == "real" and llm.errors >= 3:
            raise RuntimeError("three real LLM transport failures; incomplete trial")
    controller = model.controller
    return {"score": env.evaluate(), "actions": {kind: sum(call[0] == kind for call in env.calls)
                                                for kind in ("scan", "comm", "cut", "shield")},
            "remaining_budget": env.get_remaining_budget(), "failures": controller.action_failures,
            "llm_mode": llm_mode, "llm_model": llm.model if llm_mode == "real" else None,
            "p8_mode": p8_mode, "llm_calls": controller.llm_calls,
            "llm_accepted": controller.llm_accepted, "llm_fallbacks": controller.llm_fallbacks,
            "transport_attempts": llm.attempts, "transport_errors": llm.errors,
            "p8_proposals": controller.p8_proposals, "p8_planning_errors": controller.p8_planning_errors,
            "steps": controller.action_attempts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=FAMILIES, default="ba_negative_hubs")
    parser.add_argument("--repetition", type=int, choices=DEVELOPMENT_REPETITIONS, default=501)
    parser.add_argument("--llm-mode", choices=("real", "mock", "unavailable"), default="mock")
    parser.add_argument("--variant", choices=("conservative", "audited"), default="audited")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.llm_mode == "real":
        load_local_env(ROOT / ".env")
    seed = seed_payload(args.family, args.repetition)
    baseline = run_variant(seed, "public_greedy")
    candidate = run_trial(seed, llm_mode=args.llm_mode, p8_mode=args.variant)
    report = {"family": args.family, "repetition": args.repetition, "baseline": baseline,
              "candidate": candidate, "delta": candidate["score"] - baseline["score"],
              "evaluation": "local research with actual CaseVO orchestration", "platform_score": None,
              "production_enabled": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

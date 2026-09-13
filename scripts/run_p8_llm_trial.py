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
from starnet.policy.actions import action_cost, is_legal_action
from starnet.policy.candidates import Candidate
from starnet.policy.config import PolicyMode
from starnet.policy.p8_experiment import choose_p8_action, public_board_salt
from starnet.runtime.controller import RuntimeController
from starnet.runtime.stage import ContestStage
from starnet.submission.starnet_model import ParticipantSquadModel


class P8TrialController(RuntimeController):
    """Keep the full production executor and quota guards in a local trial."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.p8_salt = None
        self.p8_cache = {}
        self.p8_options = False
        self.p8_proposals = 0
        self.p8_planning_errors = 0

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        super()._refresh_candidates(budget, phase)
        self.p8_options = False
        if (self.effective_policy_mode is not PolicyMode.PUBLIC_GREEDY
                or len(self.blackboard.scanned_ids) != self.node_count or not self.candidates):
            return
        try:
            if self.p8_salt is None:
                self.p8_salt = public_board_salt(self.blackboard)
            decision = choose_p8_action(
                self.blackboard, budget, self.response_estimates,
                remaining_steps=max(0, self._safe_step_limit - self.action_attempts),
                salt=self.p8_salt, mode="audited", evaluation_cache=self.p8_cache,
            )
        except Exception:
            self.p8_planning_errors += 1
            return
        if not decision.deviated:
            return
        action = decision.action
        if action in self.failed_actions or not is_legal_action(action, self.blackboard, budget):
            return
        baseline = next((candidate for candidate in self.candidates.values()
                         if candidate.action == decision.baseline_action), None)
        if baseline is None:
            return
        identity = f"p8:{action.kind}:{action.target_node_1}:{action.target_node_2}:{self.blackboard.state_version}"
        gain = min(decision.mean_delta, decision.audit_mean_delta)
        # Values are continuation advantages relative to the baseline plan,
        # not immediate changes to the environment's score.
        proposed = Candidate(identity, action, 0, gain, gain / action_cost(action),
                             f"P8 assumed-response continuation advantage; selection mean={decision.mean_delta:.6f}; "
                             f"unused-scenario mean={decision.audit_mean_delta:.6f}, minimum={decision.audit_minimum_delta:.6f}; "
                             "baseline alternative has relative advantage zero", (identity,))
        fallback = Candidate(baseline.candidate_id, baseline.action, 0, 0.0, 0.0,
                             "Current public_greedy baseline; relative continuation advantage zero",
                             baseline.evidence_ids)
        self.candidates = {proposed.candidate_id: proposed, fallback.candidate_id: fallback}
        self.p8_options = True
        self.p8_proposals += 1

    def _llm_candidate_options(self, candidates):
        return candidates if self.p8_options else super()._llm_candidate_options(candidates)


class P8TrialModel(ParticipantSquadModel):
    def __init__(self, host_env, person_list, llm):
        super().__init__(host_env, person_list, llm)
        self.controller = P8TrialController(
            host_env, llm_ranker=self.commander_agent.rank_candidates,
            stage=ContestStage.PRELIMINARY, config=self.controller.config,
        )


def run_trial(seed, *, llm_mode="mock", timeout=20):
    llm = CountingLLM(timeout, offline_only=llm_mode != "real")
    env = LocalPublicEnvironment(seed)
    people = json.loads((ROOT / "src/starnet/submission/config.json").read_text())["person"]
    model = P8TrialModel(env, people, llm)
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
            "llm_mode": llm_mode, "llm_calls": controller.llm_calls,
            "llm_accepted": controller.llm_accepted, "llm_fallbacks": controller.llm_fallbacks,
            "transport_attempts": llm.attempts, "transport_errors": llm.errors,
            "p8_proposals": controller.p8_proposals, "p8_planning_errors": controller.p8_planning_errors,
            "steps": controller.action_attempts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=FAMILIES, default="ba_negative_hubs")
    parser.add_argument("--repetition", type=int, choices=DEVELOPMENT_REPETITIONS, default=501)
    parser.add_argument("--llm-mode", choices=("real", "mock", "unavailable"), default="mock")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.llm_mode == "real":
        load_local_env(ROOT / ".env")
    seed = seed_payload(args.family, args.repetition)
    baseline = run_variant(seed, "public_greedy")
    candidate = run_trial(seed, llm_mode=args.llm_mode)
    report = {"family": args.family, "repetition": args.repetition, "baseline": baseline,
              "candidate": candidate, "delta": candidate["score"] - baseline["score"],
              "evaluation": "local research with actual CaseVO orchestration", "platform_score": None,
              "production_enabled": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

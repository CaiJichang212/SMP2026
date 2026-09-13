#!/usr/bin/env python3
"""Smoke-test the generated single-file entry; qualification patches stay in memory."""

from __future__ import annotations

import copy
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_submission_archives import CountingLLM
from scripts.run_baseline_openai import load_local_env
from scripts.run_local_policy_matrix import LocalPublicEnvironment, run_variant
from scripts.run_p7_remote_probe import PairedEnvironment
from starnet.experiments.p8_seeds import seed_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    if args.real:
        load_local_env(ROOT / ".env")
    folder = ROOT / "SMP_Starter_Kit/team_submission"
    spec = importlib.util.spec_from_file_location("p8_bundle_smoke", folder / "starnet_model.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    config = json.loads((folder / "config.json").read_text())
    seed = seed_payload("ba_negative_hubs", 501)
    baseline = run_variant(seed, "public_greedy")
    original = (module.P8_CERTIFIED_MODE, module.P8_GATE_REPORT_SHA256)
    results = []
    try:
        modes = ((None, "as_built") if args.remote else ("as_built",)) if args.real else ("as_built", None, "conservative", "audited")
        for mode in modes:
            # These test-only values never modify generated files or source.
            if mode != "as_built":
                module.P8_CERTIFIED_MODE = mode
                module.P8_GATE_REPORT_SHA256 = "a" * 64 if mode else None
            else:
                module.P8_CERTIFIED_MODE, module.P8_GATE_REPORT_SHA256 = original
            people = copy.deepcopy(config["person"])
            commander = next(person for person in people if person["role"] == "CommanderAgent")
            if mode == "as_built":
                requested = commander.get("experimental_p8_mode")
                gate_path = ROOT / "experiments/reports/p8-mean-objective-result-20260913.json"
                gate = json.loads(gate_path.read_text())
                if (requested != gate["selected_variant"]
                        or not gate["variants"][requested]["mean_score_gate_passed"]
                        or module.P8_CERTIFIED_MODE != requested
                        or module.P8_GATE_REPORT_SHA256 != hashlib.sha256(gate_path.read_bytes()).hexdigest()):
                    raise RuntimeError("built qualification does not match reviewed result")
            else:
                commander["experimental_p8_mode"] = mode or "audited"
                requested = mode
            env = PairedEnvironment(seed, "http://8.222.218.162:5000", 20) if args.remote else LocalPublicEnvironment(seed)
            llm = CountingLLM(20, offline_only=not args.real)
            model = module.ParticipantSquadModel(env, people, llm)

            def choice(payload):
                candidate = payload["candidates"][0]
                return {"state_version": payload["state_version"], "mode": "single_action",
                        "candidate_id": candidate["candidate_id"], "reason_code": "bundle_mock",
                        "evidence_ids": [candidate["evidence_ids"][0]]}

            if not args.real:
                model.controller.commander.llm_ranker = choice
            while not model.controller.stopped:
                model.step()
                if model.controller.step_number > 119:
                    raise RuntimeError("bundle exceeded stage limit")
                if args.real and llm.errors >= 3:
                    raise RuntimeError("three model transport failures; incomplete compiled trial")
            score = env.evaluate()
            expected = {None: baseline["score"], "conservative": 303.6875601323529,
                        "audited": 285.52880189705877}[requested]
            if (not args.real and abs(score - expected) > 1e-8) or model.controller.action_failures:
                raise RuntimeError("compiled entry differs from tested development policy")
            if mode is None and type(model.controller).__name__ != "RuntimeController":
                raise RuntimeError("missing qualification enabled P8")
            results.append({"test_qualification": mode, "score": score,
                            "controller": type(model.controller).__name__,
                            "llm_mode": "real" if args.real else "mock",
                            "llm_model": llm.model if args.real else None,
                            "llm_calls": model.controller.llm_calls,
                            "llm_accepted": model.controller.llm_accepted,
                            "llm_fallbacks": model.controller.llm_fallbacks,
                            "transport_errors": llm.errors,
                            "action_failures": model.controller.action_failures,
                            "local_replay_score": env.local_score if args.remote else score,
                            "public_response_error": env.response_error if args.remote else None})
            print(json.dumps(results[-1]), flush=True)
    finally:
        module.P8_CERTIFIED_MODE, module.P8_GATE_REPORT_SHA256 = original
    report = {"purpose": "generated-entry equivalence and fail-closed smoke test",
              "environment": "official custom-seed sandbox" if args.remote else "local simulator",
              "qualification_patched_in_memory_only": True,
              "does_not_qualify_or_promote_a_policy": True, "results": results}
    name = "p8-compiled-real-remote-20260913.json" if args.real and args.remote else "p8-compiled-real-20260913.json" if args.real else "p8-compiled-smoke-20260913.json"
    output = ROOT / "experiments/reports" / name
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()

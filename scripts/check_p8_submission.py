#!/usr/bin/env python3
"""Smoke-test the generated single-file entry; qualification patches stay in memory."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_submission_archives import CountingLLM
from scripts.run_local_policy_matrix import LocalPublicEnvironment, run_variant
from starnet.experiments.p8_seeds import seed_payload


def main():
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
        for mode in (None, "conservative", "audited"):
            # These test-only values never modify generated files or source.
            module.P8_CERTIFIED_MODE = mode
            module.P8_GATE_REPORT_SHA256 = "a" * 64 if mode else None
            people = copy.deepcopy(config["person"])
            commander = next(person for person in people if person["role"] == "CommanderAgent")
            commander["experimental_p8_mode"] = mode or "audited"
            env = LocalPublicEnvironment(seed)
            model = module.ParticipantSquadModel(env, people, CountingLLM(20, offline_only=True))

            def choice(payload):
                candidate = payload["candidates"][0]
                return {"state_version": payload["state_version"], "mode": "single_action",
                        "candidate_id": candidate["candidate_id"], "reason_code": "bundle_mock",
                        "evidence_ids": [candidate["evidence_ids"][0]]}

            model.controller.commander.llm_ranker = choice
            while not model.controller.stopped:
                model.step()
                if model.controller.step_number > 119:
                    raise RuntimeError("bundle exceeded stage limit")
            score = env.evaluate()
            expected = {None: baseline["score"], "conservative": 303.6875601323529,
                        "audited": 285.52880189705877}[mode]
            if abs(score - expected) > 1e-8 or model.controller.action_failures:
                raise RuntimeError("compiled entry differs from tested development policy")
            if mode is None and type(model.controller).__name__ != "RuntimeController":
                raise RuntimeError("missing qualification enabled P8")
            results.append({"test_qualification": mode, "score": score,
                            "controller": type(model.controller).__name__,
                            "llm_mock_calls": model.controller.llm_calls,
                            "action_failures": model.controller.action_failures})
    finally:
        module.P8_CERTIFIED_MODE, module.P8_GATE_REPORT_SHA256 = original
    report = {"purpose": "generated-entry equivalence and fail-closed smoke test",
              "qualification_patched_in_memory_only": True,
              "does_not_qualify_or_promote_a_policy": True, "results": results}
    output = ROOT / "experiments/reports/p8-compiled-smoke-20260913.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()

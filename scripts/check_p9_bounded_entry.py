#!/usr/bin/env python3
"""Exercise an unreleased assembled candidate or exact ZIP with real CaseVO."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from scripts.build_submission import assemble_model
from scripts.compare_submission_archives import CountingLLM, extract_submission
from scripts.run_baseline_openai import load_local_env
from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p7_remote_probe import PairedEnvironment
from starnet.experiments.p9_distribution_seeds import FAMILIES, seed_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--control", action="store_true", help="Measure a historical archive without qualifying it")
    parser.add_argument("--family", choices=FAMILIES, default="ba_resampled")
    parser.add_argument("--shift", choices=("near_upper_bound", "saturated_hubs"), default="saturated_hubs")
    parser.add_argument("--repetition", type=int, choices=(901, 902), default=901)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--server-url", default="http://8.222.218.162:5000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.real:
        load_local_env(ROOT / ".env")
    seed = seed_payload(args.family, args.repetition, args.shift)
    report = {"family": args.family, "shift": args.shift, "repetition": args.repetition,
              "python_version": sys.version.split()[0],
              "seed_sha256": hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest(),
              "archive": str(args.archive) if args.archive else None,
              "unreleased_candidate_assembly": args.archive is None,
              "environment": "public custom-seed sandbox" if args.remote else "corrected local simulator",
              "llm_mode": "real" if args.real else "forced_exception_fallback",
              "platform_score": None, "complete": False}
    with TemporaryDirectory(prefix="p9-entry-") as temporary:
        folder = Path(temporary)
        if args.archive:
            config = extract_submission(args.archive, folder)
            report["archive_sha256"] = hashlib.sha256(args.archive.read_bytes()).hexdigest()
        else:
            # Test assembly is a temporary review artifact, never a qualified
            # submission. Publishing still requires build_submission's gate.
            (folder / "starnet_model.py").write_text(assemble_model(), encoding="utf-8")
            config = json.loads((ROOT / "src/starnet/submission/config.json").read_text())
            shutil.copytree(ROOT / "src/starnet/submission/prompt", folder / "prompt")
        entry = folder / "starnet_model.py"
        report["model_sha256"] = hashlib.sha256(entry.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location("p9_bounded_entry", entry)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        report["networkx_version"] = module.nx.__version__
        report["framework_model_module"] = module.ModelBase.__module__
        helper = getattr(module, "bounded_response_delta", None)
        report["bounded_estimator_active"] = bool(callable(helper) and
            helper(90.0, 15.0) == 10.0 and helper(100.0, 15.0) == 0.0
            and helper(-110.0, 3.0) == 10.0 and helper(10.0, 15.0) == 15.0)
        llm = CountingLLM(timeout=20, offline_only=not args.real)
        report["llm_model"] = llm.chat.model if args.real else None
        env = PairedEnvironment(seed, args.server_url, 20) if args.remote else LocalPublicEnvironment(seed)
        model = module.ParticipantSquadModel(env, config["person"], llm)
        started = time.monotonic()
        while not model.controller.stopped:
            model.step()
            controller = model.controller
            report.update({"steps": controller.step_number,
                           "llm_accepted": controller.llm_accepted,
                           "llm_fallbacks": controller.llm_fallbacks,
                           "llm_calls": controller.llm_calls,
                           "transport_errors": llm.errors,
                           "action_failures": controller.action_failures,
                           "p8_planning_errors": getattr(controller, "p8_planning_errors", None),
                           "p8_mode": getattr(controller, "p8_mode", None),
                           "p8_refresh_reasons": getattr(controller, "p8_refresh_reasons", None),
                           "budget": env.get_remaining_budget(),
                           "seconds": time.monotonic() - started})
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            if controller.step_number > 119 or llm.errors >= 3:
                raise RuntimeError("entry trial exceeded resource or transport-error limit")
        score = env.evaluate()
        calls = env.shadow.calls if args.remote else env.calls
        report.update({"complete": True, "score": score,
                       "local_replay_score": env.local_score if args.remote else score,
                       "public_response_error": env.response_error if args.remote else None,
                       "actions_sha256": hashlib.sha256(json.dumps(calls).encode()).hexdigest(),
                       "action_sequence": calls})
        report["entry_gate_passed"] = (
            not report["action_failures"] and not report["p8_planning_errors"]
            and report["bounded_estimator_active"]
            and report["p8_mode"] == "conservative"
            and (not args.real or report["llm_accepted"] > 0)
            and (not args.remote or report["public_response_error"] <= 1e-8)
        )
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ("action_sequence", "p8_refresh_reasons")}), flush=True)
        if not report["entry_gate_passed"] and not args.control:
            raise RuntimeError("entry validation failed")


if __name__ == "__main__":
    main()

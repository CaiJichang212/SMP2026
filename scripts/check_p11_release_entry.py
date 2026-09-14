#!/usr/bin/env python3
"""Execute an actual qualified P11 ZIP without metadata or controller injection."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.check_p11_research_entry import PROMPT_CASES, _ledger_payload
from scripts.compare_submission_archives import CountingLLM, extract_submission
from scripts.run_baseline_openai import load_local_env
from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p7_remote_probe import PairedEnvironment
from starnet.experiments.seeds import SEED_SPECS, seed_payload


LLM_MODES = ("real", "mock", "unavailable")


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest_json(value):
    return digest_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8"))


def base_report(archive, entry, seed, args):
    return {
        "schema_version": 1,
        "purpose": "Direct final P11 ZIP execution without qualification injection",
        "archive": str(archive),
        "archive_sha256": digest_bytes(archive.read_bytes()),
        "model_sha256": digest_bytes(entry.read_bytes()),
        "final_zip_execution": True,
        "unreleased_candidate_assembly": False,
        "qualification_injected_after_import": False,
        "controller_replaced_after_construction": False,
        "policy_modified": False,
        "prompt_values_visible_to_policy": False,
        "family": args.family,
        "prompt_case": args.prompt_case,
        "seed_sha256": digest_json(seed),
        "llm_mode": args.llm_mode,
        "environment": "public custom-seed sandbox" if args.remote else "corrected local simulator",
        "python_version": sys.version.split()[0],
        "entry_runner_sha256": digest_bytes(Path(__file__).read_bytes()),
        "complete": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--family", choices=tuple(SEED_SPECS), default="er_balanced")
    parser.add_argument("--prompt-case", choices=tuple(PROMPT_CASES), default="prompt2_best")
    parser.add_argument("--llm-mode", choices=LLM_MODES, default="mock")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--server-url", default="http://8.222.218.162:5000")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.timeout <= 0 or not args.archive.is_file():
        parser.error("positive timeout and existing archive are required")
    if args.llm_mode == "real":
        load_local_env(ROOT / ".env")
    values = PROMPT_CASES[args.prompt_case]
    seed = copy.deepcopy(seed_payload(args.family, 50, 1))
    seed["prompts"] = {str(index): value for index, value in enumerate(values, 1)}
    best = max(values)
    best_ids = tuple(index for index, value in enumerate(values, 1) if value == best)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    previous_cwd = Path.cwd()
    report = None
    try:
        with TemporaryDirectory(prefix="p11-final-entry-") as directory:
            folder = Path(directory)
            config = extract_submission(args.archive, folder)
            entry = folder / "starnet_model.py"
            report = base_report(args.archive, entry, seed, args)
            os.chdir(folder)
            module_name = f"p11_final_entry_{os.getpid()}"
            spec = importlib.util.spec_from_file_location(module_name, entry)
            if spec is None or spec.loader is None:
                raise RuntimeError("cannot load final P11 ZIP entry")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            llm = CountingLLM(args.timeout, offline_only=args.llm_mode != "real")
            env = (PairedEnvironment(seed, args.server_url, args.timeout)
                   if args.remote else LocalPublicEnvironment(seed))
            model = module.ParticipantSquadModel(env, config["person"], llm)
            controller = model.controller
            decisions = []
            if args.llm_mode == "mock":
                def rank(payload):
                    item = payload["candidates"][0]
                    decisions.append({
                        "state_version": payload["state_version"],
                        "candidate_ids": [candidate["candidate_id"]
                                          for candidate in payload["candidates"]],
                        "selected_candidate_id": item["candidate_id"],
                    })
                    return {
                        "state_version": payload["state_version"], "mode": "single_action",
                        "candidate_id": item["candidate_id"], "reason_code": "p11_final_zip",
                        "evidence_ids": [item["evidence_ids"][0]],
                    }
                controller.commander.llm_ranker = rank
            maximum = 0
            for host_calls in range(1, 121):
                calls = env.shadow.calls if args.remote else env.calls
                before = len(calls)
                status = model.step()
                maximum = max(maximum, len(calls) - before)
                if maximum > 1:
                    raise RuntimeError("final P11 ZIP issued multiple actions in one host step")
                if status or controller.stopped:
                    break
                if args.llm_mode == "real" and llm.errors >= 3:
                    raise RuntimeError("three final P11 ZIP LLM transport failures")
            if not controller.stopped and host_calls >= 120:
                raise RuntimeError("final P11 ZIP reached host-call cap without stopping")
            calls = env.shadow.calls if args.remote else env.calls
            selected = getattr(controller, "p11_selected_prompt_id", None)
            first_intervention = next((index for index, call in enumerate(calls)
                                       if call[0] != "scan"), len(calls))
            attempts = getattr(controller, "p11_probe_attempts", 0)
            probe_calls = calls[first_intervention:first_intervention + attempts]
            selected_dispatches = [
                call for call in calls[first_intervention + attempts:]
                if call[0] == "comm" and len(call) > 2 and call[2] == selected
            ]
            result = {
                "score": env.evaluate(),
                "local_replay_score": env.local_score if args.remote else env.evaluate(),
                "public_response_error": env.response_error if args.remote else None,
                "remaining_budget": env.get_remaining_budget(),
                "host_calls": host_calls,
                "action_attempts": controller.action_attempts,
                "one_action_per_host_step": maximum <= 1,
                "max_actions_per_host_step": maximum,
                "action_sha256": digest_json(calls),
                "action_sequence": calls,
                "probe_action_sequence": probe_calls,
                "model_decisions": decisions,
                "llm_calls": controller.llm_calls,
                "llm_accepted": controller.llm_accepted,
                "llm_fallbacks": controller.llm_fallbacks,
                "transport_errors": llm.errors,
                "action_failures": controller.action_failures,
                "p8_planning_errors": getattr(controller, "p8_planning_errors", None),
                "p11_planning_errors": getattr(controller, "p11_planning_errors", None),
                "p11_experiment_mode": getattr(controller, "p11_experiment_mode", None),
                "p11_enabled": getattr(controller, "p11_enabled", None),
                "p11_calibration_finished": getattr(controller, "p11_calibration_finished", None),
                "p11_selected_prompt_id": selected,
                "p11_selected_prompt_prior": getattr(controller, "p11_selected_prompt_prior", None),
                "p11_probe_nodes": list(getattr(controller, "p11_probe_nodes", ())),
                "p11_probe_attempts": attempts,
                "p11_probe_successes": getattr(controller, "p11_probe_successes", None),
                "p11_probe_failures": getattr(controller, "p11_probe_failures", None),
                "p11_probe_budget": getattr(controller, "p11_probe_budget", None),
                "p11_fallback_to_p9": getattr(controller, "p11_fallback_to_p9", None),
                "p11_errors": getattr(controller, "p11_errors", None),
                "p11_last_error": getattr(controller, "p11_last_error", None),
                "p11_response_switches": getattr(controller, "p11_response_switches", None),
                "selected_prompt_dispatch_count": len(selected_dispatches),
                "selected_prompt_observations": getattr(
                    controller, "p11_selected_prompt_observations", None,
                ),
                "selected_response_censored": getattr(
                    controller, "p11_selected_response_censored", None,
                ),
                "ledger": _ledger_payload(controller),
            }
            report.update({
                "networkx_version": module.nx.__version__,
                "framework_model_module": module.ModelBase.__module__,
                "agent_base_module": module.AgentBase.__module__,
                "controller_type": type(controller).__name__,
                **{key: result[key] for key in (
                    "p11_experiment_mode", "p11_enabled", "p11_calibration_finished",
                    "p11_selected_prompt_id", "p11_probe_attempts", "p11_probe_successes",
                    "p11_probe_failures", "p11_probe_budget", "p11_fallback_to_p9",
                    "p11_errors", "p11_last_error", "p11_response_switches",
                    "selected_prompt_dispatch_count", "action_failures",
                    "p8_planning_errors", "p11_planning_errors",
                    "one_action_per_host_step", "max_actions_per_host_step", "action_sha256",
                )},
                "result": result,
            })
            report["entry_gate_passed"] = (
                type(controller).__name__ == "PromptLearningRuntimeController"
                and result["p11_experiment_mode"] == "prompt_learning"
                and result["p11_enabled"] is True
                and result["p11_calibration_finished"] is True
                and selected in best_ids and attempts <= 6
                and 0.0 <= result["p11_probe_budget"] <= 12.0
                and maximum <= 1 and result["action_failures"] == 0
                and result["p8_planning_errors"] == 0
                and result["p11_planning_errors"] == 0
                and result["p11_errors"] == 0 and result["p11_last_error"] is None
                and len(selected_dispatches) > 0
                and (not args.remote or result["public_response_error"] <= 1e-8)
                and (args.llm_mode != "real" or
                     (result["llm_accepted"] > 0 and result["transport_errors"] == 0))
            )
            report["complete"] = True
    except Exception as exc:
        if report is None:
            report = {"archive": str(args.archive), "complete": False}
        report["error_type"] = type(exc).__name__
        report["entry_gate_passed"] = False
        raise
    finally:
        os.chdir(previous_cwd)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                               encoding="utf-8")
    print(json.dumps({"complete": report["complete"],
                      "entry_gate_passed": report["entry_gate_passed"],
                      "archive_sha256": report["archive_sha256"],
                      "model_sha256": report["model_sha256"],
                      "selected_prompt": report["p11_selected_prompt_id"],
                      "probe_budget": report["p11_probe_budget"],
                      "dispatches": report["selected_prompt_dispatch_count"],
                      "score": report["result"]["score"]}), flush=True)
    return 0 if report["entry_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assemble and exercise the isolated P11 prompt-learning entry."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.build_submission import INLINE_MODULES, strip_project_imports
from scripts.check_p10_research_entry import (
    _first_divergence,
    _run_p9_baseline,
    digest_bytes,
    digest_json,
    source_collision_audit,
)
from scripts.compare_submission_archives import CountingLLM
from scripts.run_baseline_openai import load_local_env
from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p7_remote_probe import PairedEnvironment
from scripts.submission_loader_compat import LOADER_COMPAT_PREAMBLE
from starnet.experiments.seeds import SEED_SPECS, seed_payload


EXPERIMENT_MODULES = (
    "src/starnet/policy/prompt_calibration_experiment.py",
    "src/starnet/runtime/p11_prompt_controller_experiment.py",
)
PROMPT_CASES = {
    "prompt1_best": (15.0, 10.0, -5.0),
    "prompt2_best": (-5.0, 15.0, 10.0),
    "prompt3_best": (10.0, -5.0, 15.0),
    "tie_nonharmful": (-5.0, 15.0, 15.0),
    "all_negative": (-5.0, -2.0, -4.0),
    "all_positive_tie": (3.0, 3.0, 3.0),
}
LLM_MODES = ("real", "mock", "unavailable")


def assemble_p11_entry():
    ordered = tuple(dict.fromkeys(INLINE_MODULES))
    collisions = source_collision_audit(ordered)
    source_hashes = {}
    chunks = ["from __future__ import annotations\n\n", LOADER_COMPAT_PREAMBLE, "\n"]
    for relative in ordered:
        path = ROOT / relative
        raw = path.read_text(encoding="utf-8")
        source_hashes[relative] = digest_bytes(raw.encode("utf-8"))
        chunks.extend((f"# Begin inline: {relative}\n", strip_project_imports(raw, path),
                       f"\n# End inline: {relative}\n\n"))
    source = "".join(chunks).rstrip() + "\n"
    tree = ast.parse(source, filename="p11_research_entry.py", feature_version=(3, 9))
    residual = []
    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
        elif isinstance(node, ast.Import):
            modules = [item.name for item in node.names]
            if any(item == "starnet" or item.startswith("starnet.") for item in modules):
                residual.append({"line": node.lineno, "modules": modules})
        if module is not None and (module == "starnet" or module.startswith("starnet.")):
            residual.append({"line": node.lineno, "modules": [module]})
    if collisions or residual:
        raise RuntimeError("P11 single-file isolation audit failed")
    return source, {
        "ordered_sources": list(ordered), "source_sha256": source_hashes,
        "top_level_collisions": collisions, "residual_starnet_imports": residual,
        "python39_ast_passed": True,
    }


def _ledger_payload(controller):
    ledger = controller.p11_prompt_ledger
    return {
        "confident": ledger.confident,
        "calibration_complete": ledger.calibration_complete,
        "calibrated_prompt_id": ledger.calibrated_prompt_id,
        "calibrated_prompt_ids": list(ledger.calibrated_prompt_ids),
        "provisional_prompt_ids": list(ledger.provisional_prompt_ids),
        "informative_node_ids": list(ledger.informative_node_ids),
        "node_rankings": {str(key): list(value) for key, value in ledger.node_rankings().items()},
        "normalized_values": ledger.normalized_values(),
        "accepted": ledger.accepted, "censored": ledger.censored,
        "failures": ledger.failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=tuple(SEED_SPECS), default="er_balanced")
    parser.add_argument("--prompt-case", choices=tuple(PROMPT_CASES), default="prompt2_best")
    parser.add_argument("--llm-mode", choices=LLM_MODES, default="mock")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--baseline-p9", action="store_true")
    parser.add_argument("--strip-p11-config-field", action="store_true")
    parser.add_argument("--server-url", default="http://8.222.218.162:5000")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    if args.llm_mode == "real":
        load_local_env(ROOT / ".env")
    source_before = {
        relative: digest_bytes((ROOT / relative).read_bytes())
        for relative in (*INLINE_MODULES, *EXPERIMENT_MODULES)
    }
    assembled, audit = assemble_p11_entry()
    prompt_values = PROMPT_CASES[args.prompt_case]
    seed = copy.deepcopy(seed_payload(args.family, 50, 1))
    seed["prompts"] = {str(index): value for index, value in enumerate(prompt_values, 1)}
    best_value = max(prompt_values)
    true_best = tuple(index for index, value in enumerate(prompt_values, 1)
                      if value == best_value)
    report = {
        "schema_version": 1,
        "purpose": "Unqualified temporary P11 research entry validation",
        "production_enabled": False,
        "qualification_modified": False,
        "canonical_entry_modified": False,
        "prompt_values_visible_to_policy": False,
        "family": args.family,
        "prompt_case": args.prompt_case,
        "true_best_prompt_ids": list(true_best),
        "seed_sha256": digest_json(seed),
        "llm_mode": args.llm_mode,
        "environment": "public custom-seed sandbox" if args.remote else "corrected local simulator",
        "python_version": sys.version.split()[0],
        "entry_runner_sha256": digest_bytes(Path(__file__).read_bytes()),
        "assembly": audit,
        "model_sha256": digest_bytes(assembled.encode("utf-8")),
        "complete": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    previous_cwd = Path.cwd()
    try:
        with TemporaryDirectory(prefix="p11-research-entry-") as directory:
            folder = Path(directory)
            entry = folder / "starnet_model.py"
            entry.write_text(assembled, encoding="utf-8")
            shutil.copytree(ROOT / "src/starnet/submission/prompt", folder / "prompt")
            os.chdir(folder)
            module_name = f"p11_research_entry_{os.getpid()}"
            spec = importlib.util.spec_from_file_location(module_name, entry)
            if spec is None or spec.loader is None:
                raise RuntimeError("cannot load P11 research entry")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            activation_metadata = {
                "P11_CERTIFIED_MODE": "prompt_learning",
                "P11_GATE_REPORT_SHA256": "a" * 64,
                "P11_GATE_REPORT_RELATIVE_PATH": "experiments/reports/p11-research-only.json",
            }
            for name, value in activation_metadata.items():
                setattr(module, name, value)
            report["temporary_qualification_metadata"] = activation_metadata
            report["qualification_injected_after_import"] = True
            llm = CountingLLM(args.timeout, offline_only=args.llm_mode != "real")
            env = (PairedEnvironment(seed, args.server_url, args.timeout)
                   if args.remote else LocalPublicEnvironment(seed))
            people = json.loads(
                (ROOT / "src/starnet/submission/config.json").read_text(encoding="utf-8")
            )["person"]
            if args.strip_p11_config_field:
                people = copy.deepcopy(people)
                for description in people:
                    if isinstance(description, dict):
                        description.pop("experimental_p11_mode", None)
            report["p11_config_field_stripped"] = args.strip_p11_config_field
            model = module.ParticipantSquadModel(env, people, llm)
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
                        "candidate_id": item["candidate_id"], "reason_code": "p11_entry_check",
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
                    raise RuntimeError("P11 issued multiple actions in one host step")
                if status or controller.stopped:
                    break
                if args.llm_mode == "real" and llm.errors >= 3:
                    raise RuntimeError("three P11 LLM transport failures")
            if not controller.stopped and host_calls >= 120:
                raise RuntimeError("P11 reached host-call cap without stopping")
            calls = env.shadow.calls if args.remote else env.calls
            selected = controller.p11_selected_prompt_id
            first_intervention = next((index for index, call in enumerate(calls)
                                       if call[0] != "scan"), len(calls))
            probe_calls = calls[first_intervention:first_intervention + controller.p11_probe_attempts]
            selected_dispatches = [
                call for call in calls[first_intervention + controller.p11_probe_attempts:]
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
                "p8_planning_errors": controller.p8_planning_errors,
                "p11_planning_errors": controller.p11_planning_errors,
                "p11_experiment_mode": controller.p11_experiment_mode,
                "p11_enabled": controller.p11_enabled,
                "p11_calibration_finished": controller.p11_calibration_finished,
                "p11_selected_prompt_id": selected,
                "p11_selected_prompt_prior": controller.p11_selected_prompt_prior,
                "p11_prompt_positive": controller.p11_prompt_positive,
                "p11_probe_nodes": list(controller.p11_probe_nodes),
                "p11_probe_attempts": controller.p11_probe_attempts,
                "p11_probe_successes": controller.p11_probe_successes,
                "p11_probe_failures": controller.p11_probe_failures,
                "p11_probe_budget": controller.p11_probe_budget,
                "p11_fallback_to_p9": controller.p11_fallback_to_p9,
                "p11_errors": controller.p11_errors,
                "p11_last_error": controller.p11_last_error,
                "p11_response_switches": controller.p11_response_switches,
                "selected_prompt_dispatch_count": len(selected_dispatches),
                "selected_observation_attempts": controller.p11_selected_prompt_dispatches,
                "selected_prompt_observations": controller.p11_selected_prompt_observations,
                "selected_response_censored": controller.p11_selected_response_censored,
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
                and controller.p11_experiment_mode == "prompt_learning"
                and controller.p11_enabled and controller.p11_calibration_finished
                and selected in true_best
                and controller.p11_probe_attempts <= 6
                and controller.p11_probe_budget <= 12.0
                and maximum <= 1 and controller.action_failures == 0
                and controller.p8_planning_errors == 0
                and controller.p11_planning_errors == 0 and controller.p11_errors == 0
                and (not args.remote or result["public_response_error"] <= 1e-8)
                and (args.llm_mode != "real" or controller.llm_accepted > 0)
            )
            report["complete"] = True
        os.chdir(previous_cwd)
        if args.baseline_p9:
            baseline_args = SimpleNamespace(**vars(args))
            if baseline_args.llm_mode == "mock":
                baseline_args.llm_mode = "mock-plan"
            baseline = _run_p9_baseline(seed, baseline_args)
            report["baseline_p9"] = baseline
            report["paired"] = {
                "score_delta": report["result"]["score"] - baseline["score"],
                "first_divergence": _first_divergence(
                    report["result"]["action_sequence"], baseline["action_sequence"],
                ),
            }
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["entry_gate_passed"] = False
        raise
    finally:
        os.chdir(previous_cwd)
        report["source_unchanged"] = source_before == {
            relative: digest_bytes((ROOT / relative).read_bytes())
            for relative in (*INLINE_MODULES, *EXPERIMENT_MODULES)
        }
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                               encoding="utf-8")
    print(json.dumps({
        "complete": report["complete"], "entry_gate_passed": report["entry_gate_passed"],
        "selected_prompt": report["p11_selected_prompt_id"],
        "probe_budget": report["p11_probe_budget"],
        "dispatches": report["selected_prompt_dispatch_count"],
        "score": report["result"]["score"],
        "errors": {key: report[key] for key in
                   ("action_failures", "p8_planning_errors", "p11_planning_errors", "p11_errors")},
    }), flush=True)
    return 0 if report["entry_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

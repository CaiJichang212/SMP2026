#!/usr/bin/env python3
"""Assemble and exercise an unqualified P10 research entry with real CaseVO."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.build_submission import INLINE_MODULES, strip_project_imports
from scripts.compare_submission_archives import CountingLLM
from scripts.run_baseline_openai import load_local_env
from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p7_remote_probe import PairedEnvironment
from scripts.submission_loader_compat import LOADER_COMPAT_PREAMBLE
from starnet.experiments.p8_seeds import DEVELOPMENT_REPETITIONS, FAMILIES, seed_payload


EXPERIMENT_MODULES = (
    "src/starnet/policy/public_response_mixture.py",
    "src/starnet/policy/p9_prefix_experiment.py",
    "src/starnet/policy/p10_structure_plan_experiment.py",
    "src/starnet/runtime/p10_controller_experiment.py",
)
VARIANTS = ("plan_only", "response_only", "combined")
LLM_MODES = ("real", "mock-plan", "mock-baseline", "unavailable")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: object) -> str:
    return digest_bytes(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8"))


def _top_level_bindings(source: str, path: Path) -> set[str]:
    result = set()
    for node in ast.parse(source, filename=str(path)).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result.add(node.name)
        elif isinstance(node, ast.Assign):
            result.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            result.add(node.target.id)
    result.discard("__all__")
    return result


def source_collision_audit(paths: tuple[str, ...]) -> list[dict[str, str]]:
    owners: dict[str, str] = {}
    collisions = []
    for relative in paths:
        path = ROOT / relative
        for name in sorted(_top_level_bindings(path.read_text(encoding="utf-8"), path)):
            previous = owners.get(name)
            if previous is not None:
                collisions.append({"name": name, "first": previous, "second": relative})
            else:
                owners[name] = relative
    return collisions


def _research_entry(variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError("unknown P10 research variant")
    return f'''\n# Begin isolated P10 research entry\n
_P10CanonicalParticipantSquadModel = ParticipantSquadModel


class ParticipantSquadModel(_P10CanonicalParticipantSquadModel):
    def __init__(self, host_env, person_list, llm):
        super().__init__(host_env, person_list, llm)
        self.controller = P10RuntimeController(
            host_env,
            llm_ranker=self.commander_agent.rank_candidates,
            stage=ContestStage.PRELIMINARY,
            config=self.controller.config,
            p8_mode="conservative",
            max_structures=12,
            beam_width=4,
            experiment_mode={variant!r},
            require_stage_envelope=False,
        )

# End isolated P10 research entry\n'''


def assemble_research_entry(variant: str) -> tuple[str, dict[str, object]]:
    ordered = (*INLINE_MODULES[:-1], *EXPERIMENT_MODULES, INLINE_MODULES[-1])
    collisions = source_collision_audit(ordered)
    chunks = ["from __future__ import annotations\n\n", LOADER_COMPAT_PREAMBLE, "\n"]
    source_hashes = {}
    for relative in ordered:
        path = ROOT / relative
        raw = path.read_text(encoding="utf-8")
        source_hashes[relative] = digest_bytes(raw.encode("utf-8"))
        chunks.extend((f"# Begin inline: {relative}\n", strip_project_imports(raw, path),
                       f"\n# End inline: {relative}\n\n"))
    chunks.append(_research_entry(variant))
    assembled = "".join(chunks).rstrip() + "\n"
    tree = ast.parse(assembled, filename="p10_research_entry.py", feature_version=(3, 9))
    residual = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        if any(name == "starnet" or name.startswith("starnet.") for name in names):
            residual.append({"line": node.lineno, "modules": names})
    if collisions or residual:
        raise RuntimeError("P10 research assembly failed static isolation audit")
    return assembled, {
        "ordered_sources": list(ordered),
        "source_sha256": source_hashes,
        "top_level_collisions": collisions,
        "residual_starnet_imports": residual,
        "python39_ast_passed": True,
        "intentional_entry_alias": "ParticipantSquadModel replaces the canonical class only in the temporary bundle",
    }


def _action_payload(action):
    if action is None:
        return None
    return {
        "kind": action.kind, "target_node_1": action.target_node_1,
        "target_node_2": action.target_node_2, "prompt_id": action.prompt_id,
    }


def _action_call(action):
    if action.kind == "comm":
        return ("comm", action.target_node_1, action.prompt_id)
    if action.kind == "cut":
        return ("cut", action.target_node_1, action.target_node_2)
    return (action.kind, action.target_node_1)


def _plan_payload(controller):
    plan = getattr(controller, "p10_plan", None)
    decision = getattr(controller, "p10_decision", None)
    return {
        "search_completed": getattr(controller, "p10_search_completed", False),
        "plan": None if plan is None else {
            "structure_actions": [_action_payload(action) for action in plan.structure_actions],
            "persuasion_actions": [_action_payload(action) for action in plan.persuasion_actions],
            "predicted_score": plan.predicted_score,
            "baseline_score": plan.baseline_score,
            "root_actions": plan.root_actions,
            "expanded_states": plan.expanded_states,
            "planning_seconds": plan.planning_seconds,
        },
        "decision": None if decision is None else {
            "baseline_action": _action_payload(decision.baseline_action),
            "selection_deltas": list(decision.selection_deltas),
            "audit_deltas": list(decision.audit_deltas),
            "accepted": decision.accepted,
            "rollouts": decision.rollouts,
        },
    }


def _mixture_payload(controller):
    estimator = getattr(controller, "p10_response_estimator", None)
    gate = False
    if estimator is not None and not getattr(controller, "p10_response_disabled", False):
        gate_fn = getattr(estimator, "gate_open", None)
        gate = bool(gate_fn()) if callable(gate_fn) else False
    return {
        "configured": estimator is not None,
        "gate_open": gate,
        "activation": getattr(estimator, "activation", None),
        "accepted_observations": len(getattr(estimator, "accepted", ())),
        "censored_observations": len(getattr(estimator, "censored", ())),
        "disabled": getattr(controller, "p10_response_disabled", False),
        "disable_reason": getattr(controller, "p10_response_disable_reason", None),
        "switches": getattr(controller, "p10_response_switches", 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=VARIANTS, default="combined")
    parser.add_argument("--family", choices=FAMILIES, default="ba_negative_hubs")
    parser.add_argument("--repetition", type=int, choices=DEVELOPMENT_REPETITIONS, default=501)
    parser.add_argument("--llm-mode", choices=LLM_MODES, default="mock-plan")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--server-url", default="http://8.222.218.162:5000")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    if args.llm_mode == "real":
        load_local_env(ROOT / ".env")

    source_hash_before = {
        relative: digest_bytes((ROOT / relative).read_bytes())
        for relative in (*INLINE_MODULES, *EXPERIMENT_MODULES)
    }
    assembled, audit = assemble_research_entry(args.variant)
    seed = seed_payload(args.family, args.repetition)
    report = {
        "schema_version": 1,
        "purpose": "Unqualified temporary P10 research entry validation",
        "production_enabled": False,
        "qualification_modified": False,
        "canonical_build_modified": False,
        "variant": args.variant,
        "family": args.family,
        "repetition": args.repetition,
        "seed_sha256": digest_json(seed),
        "llm_mode": args.llm_mode,
        "environment": "public custom-seed sandbox" if args.remote else "corrected local simulator",
        "python_version": sys.version.split()[0],
        "assembly": audit,
        "assembled_model_sha256": digest_bytes(assembled.encode("utf-8")),
        "complete": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    previous_cwd = Path.cwd()
    try:
        with TemporaryDirectory(prefix="p10-research-entry-") as directory:
            folder = Path(directory)
            entry = folder / "starnet_model.py"
            entry.write_text(assembled, encoding="utf-8")
            shutil.copytree(ROOT / "src/starnet/submission/prompt", folder / "prompt")
            os.chdir(folder)
            module_name = f"p10_research_entry_{os.getpid()}"
            spec = importlib.util.spec_from_file_location(module_name, entry)
            if spec is None or spec.loader is None:
                raise RuntimeError("cannot load temporary P10 entry")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            report.update({
                "networkx_version": module.nx.__version__,
                "framework_model_module": module.ModelBase.__module__,
                "agent_base_module": module.AgentBase.__module__,
                "temporary_model_path_retained": False,
            })
            llm = CountingLLM(args.timeout, offline_only=args.llm_mode != "real")
            env = (PairedEnvironment(seed, args.server_url, args.timeout)
                   if args.remote else LocalPublicEnvironment(seed))
            people = json.loads(
                (ROOT / "src/starnet/submission/config.json").read_text(encoding="utf-8")
            )["person"]
            model = module.ParticipantSquadModel(env, people, llm)
            controller = model.controller
            mock_decisions = []
            if args.llm_mode.startswith("mock-"):
                def rank(payload):
                    candidates = payload["candidates"]
                    plan = [item for item in candidates
                            if item["candidate_id"].startswith("p10-plan:")]
                    if args.llm_mode == "mock-plan" and plan:
                        item = plan[0]
                    elif args.llm_mode == "mock-baseline" and plan:
                        item = next(item for item in candidates
                                    if not item["candidate_id"].startswith("p10-plan:"))
                    else:
                        item = candidates[0]
                    mock_decisions.append({
                        "state_version": payload["state_version"],
                        "candidate_ids": [candidate["candidate_id"] for candidate in candidates],
                        "selected_candidate_id": item["candidate_id"],
                    })
                    return {
                        "state_version": payload["state_version"], "mode": "single_action",
                        "candidate_id": item["candidate_id"], "reason_code": "p10_entry_check",
                        "evidence_ids": [item["evidence_ids"][0]],
                    }
                controller.commander.llm_ranker = rank

            max_actions_per_step = 0
            started = time.monotonic()
            for host_calls in range(1, 121):
                calls = env.shadow.calls if args.remote else env.calls
                before = len(calls)
                status = model.step()
                issued = len(calls) - before
                max_actions_per_step = max(max_actions_per_step, issued)
                if issued > 1:
                    raise RuntimeError("P10 entry issued multiple actions in one host step")
                if status or controller.stopped:
                    break
                if args.llm_mode == "real" and llm.errors >= 3:
                    raise RuntimeError("three real LLM transport failures")
            if not controller.stopped and host_calls >= 120:
                raise RuntimeError("P10 entry reached host-call cap without stopping")
            calls = env.shadow.calls if args.remote else env.calls
            plan = _plan_payload(controller)
            mixture = _mixture_payload(controller)
            expected_prefix = (
                tuple(_action_call(action) for action in controller.p10_plan.structure_actions)
                if controller.p10_plan is not None and controller.p10_approved_plans else ()
            )
            first_intervention = next(
                (index for index, call in enumerate(calls) if call[0] != "scan"),
                len(calls),
            )
            actual_prefix = tuple(calls[first_intervention:first_intervention + len(expected_prefix)])
            result = {
                "controller_type": type(controller).__name__,
                "experiment_mode": controller.p10_experiment_mode,
                "score": env.evaluate(),
                "local_replay_score": env.local_score if args.remote else env.evaluate(),
                "public_response_error": env.response_error if args.remote else None,
                "remaining_budget": env.get_remaining_budget(),
                "host_calls": host_calls,
                "action_attempts": controller.action_attempts,
                "one_step_one_action": max_actions_per_step <= 1,
                "max_actions_per_step": max_actions_per_step,
                "actions_sha256": digest_json(calls),
                "action_sequence": calls,
                "llm_calls": controller.llm_calls,
                "llm_accepted": controller.llm_accepted,
                "llm_fallbacks": controller.llm_fallbacks,
                "transport_errors": llm.errors,
                "action_failures": controller.action_failures,
                "p8_planning_errors": controller.p8_planning_errors,
                "p10_searches": controller.p10_searches,
                "p10_planning_errors": controller.p10_planning_errors,
                "p10_last_planning_error": controller.p10_last_planning_error,
                "p10_approved_plans": controller.p10_approved_plans,
                "p10_baseline_choices": controller.p10_baseline_choices,
                "p10_prefix_successes": controller.p10_prefix_successes,
                "p10_prefix_failures": controller.p10_prefix_failures,
                "p10_prefix_completed": controller.p10_prefix_completed,
                "approved_plan_expected_prefix": [list(call) for call in expected_prefix],
                "approved_plan_actual_prefix": [list(call) for call in actual_prefix],
                "approved_plan_execution_matches": actual_prefix == expected_prefix,
                "plan": plan,
                "mixture": mixture,
                "mock_decisions": mock_decisions,
                "seconds": time.monotonic() - started,
            }
            report["result"] = result
            plan_required = args.variant in ("plan_only", "combined")
            report["entry_gate_passed"] = (
                controller.p10_experiment_mode == args.variant
                and type(controller).__name__ == "P10RuntimeController"
                and not audit["top_level_collisions"]
                and not audit["residual_starnet_imports"]
                and result["one_step_one_action"]
                and result["action_failures"] == 0
                and result["p8_planning_errors"] == 0
                and result["p10_planning_errors"] == 0
                and result["p10_prefix_failures"] == 0
                and (not result["p10_approved_plans"]
                     or (result["approved_plan_execution_matches"]
                         and result["p10_prefix_completed"] == result["p10_approved_plans"]))
                and (not plan_required or result["p10_searches"] == 1)
                and (not args.remote or result["public_response_error"] <= 1e-8)
                and (args.llm_mode != "real" or result["llm_accepted"] > 0)
            )
            report["complete"] = True
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["entry_gate_passed"] = False
        raise
    finally:
        os.chdir(previous_cwd)
        report["source_unchanged"] = source_hash_before == {
            relative: digest_bytes((ROOT / relative).read_bytes())
            for relative in (*INLINE_MODULES, *EXPERIMENT_MODULES)
        }
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                               encoding="utf-8")
    print(json.dumps({
        "complete": report["complete"], "entry_gate_passed": report["entry_gate_passed"],
        "variant": args.variant, "score": report["result"]["score"],
        "approved_plans": report["result"]["p10_approved_plans"],
        "prefix_completed": report["result"]["p10_prefix_completed"],
        "mixture_gate_open": report["result"]["mixture"]["gate_open"],
        "errors": {key: report["result"][key] for key in
                   ("action_failures", "p8_planning_errors", "p10_planning_errors")},
    }), flush=True)
    return 0 if report["entry_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

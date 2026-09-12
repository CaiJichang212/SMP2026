#!/usr/bin/env python3
"""Compare unchanged historical ZIP entry points on paired local seeds."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from zipfile import ZipFile

try:
    from scripts.run_baseline_openai import OpenAICompatibleLLM, load_local_env
    from scripts.openai_compat import DEFAULT_BASE_URL, DEFAULT_MODEL
    from scripts.run_local_policy_matrix import LocalPublicEnvironment
except ModuleNotFoundError as exc:
    if exc.name != "scripts":
        raise
    from run_baseline_openai import OpenAICompatibleLLM, load_local_env
    from openai_compat import DEFAULT_BASE_URL, DEFAULT_MODEL
    from run_local_policy_matrix import LocalPublicEnvironment
from starnet.experiments.seeds import SEED_SPECS, seed_payload


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = {
    # These locally built 2026-09-12 archives have no separate platform score
    # attached. Keeping them here permits the same paired local runner used
    # for the historical submission comparison.
    "starnet-control-after-p6-20260912.zip": None,
    "starnet-prefilter-equivalent-20260912.zip": None,
    "starnet-public-greedy-llm-20260912.zip": None,
    "starnet-public-greedy-llm-control-20260912.zip": None,
    "starnet-public-greedy-llm-candidate-20260912.zip": 761.9467,
    "starnet-public-greedy-v9-optimized-20260908.zip": 761.9467,
    "starnet-b1-risk-aware-source-20260908.zip": 550.9400,
    "starnet-public-greedy-risk-aware-20260908.zip": 731.4633,
    "starnet-public-greedy-experimental-20260908.zip": 765.8400,
    "starnet-b1-v4-default-20260908.zip": 550.9400,
    "v1-cmg.zip": 655.3267,
    "v1-experiment-tools.zip": 655.3267,
    "v0-baseline-0904-1.zip": 655.3267,
    "starnet-public-greedy-llm-audited-20260912.zip": None,
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_submission(archive: Path, target: Path) -> dict:
    with ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise ValueError("unsafe archive member")
            if not path.parts or path.parts[0] not in {"config.json", "prompt", "starnet_model.py"}:
                raise ValueError("unexpected archive root entry")
        bundle.extractall(target)
    return json.loads((target / "config.json").read_text(encoding="utf-8"))


class CurrentRulesEnvironment(LocalPublicEnvironment):
    """Apply the clarified failure charges without changing archived code."""

    def cut_link(self, left: int, right: int) -> bool:
        before = self.budget
        success = super().cut_link(left, right)
        if not success and before >= 3.0:
            self.budget = before - 3.0
        return success

    def shield_node(self, node_id: int) -> bool:
        before = self.budget
        success = super().shield_node(node_id)
        if not success and before >= 5.0:
            self.budget = before - 5.0
        return success


class CountingLLM(OpenAICompatibleLLM):
    def __init__(self, timeout: float, offline_only: bool = False):
        super().__init__(
            "offline-unused" if offline_only else os.environ["SMP_LLM_API_KEY"],
            os.getenv("SMP_LLM_BASE_URL", DEFAULT_BASE_URL),
            os.getenv("SMP_LLM_MODEL", DEFAULT_MODEL), timeout,
        )
        self.attempts = 0
        self.errors = 0
        self.offline_only = offline_only
        self.blocked_calls = 0

    def send_message(self, prompt: str, json_flag: bool = False) -> str:
        if self.offline_only:
            self.blocked_calls += 1
            raise RuntimeError("network disabled for offline archive validation")
        if self.attempts >= 120:
            raise RuntimeError("stage LLM quota exhausted")
        self.attempts += 1
        try:
            return super().send_message(prompt, json_flag)
        except Exception:
            self.errors += 1
            raise


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def worker(job_path: Path) -> int:
    job = json.loads(job_path.read_text())
    result_path = Path(job["result_path"])
    archive = Path(job["archive"])
    started = time.monotonic()
    result = {"archive": archive.name, "archive_sha256": digest(archive.read_bytes()),
              "runner_sha256": digest(Path(__file__).read_bytes()),
              "family": job["family"], "repetition": 1, "node_count": 50}
    previous_cwd = Path.cwd()
    try:
        load_local_env(ROOT / ".env")
        seed = seed_payload(job["family"], 50, 1)
        result["seed_sha256"] = digest(json.dumps(seed, sort_keys=True).encode())
        env = CurrentRulesEnvironment(seed)
        llm = CountingLLM(job["timeout"], job.get("offline_only", False))
        result["offline_only"] = llm.offline_only
        result["allow_offline_fallback"] = job.get("allow_offline_fallback", False)
        with TemporaryDirectory(prefix="starnet-archive-") as directory:
            folder = Path(directory)
            config = extract_submission(archive, folder)
            os.chdir(folder)
            module_name = "historical_submission"
            spec = importlib.util.spec_from_file_location(module_name, folder / "starnet_model.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            model = module.ParticipantSquadModel(env, config["person"], llm)
            result["archive_config"] = config
            policy_config = getattr(model.controller, "config", None)
            result["effective_policy_config"] = (
                asdict(policy_config) if policy_config is not None
                else {"legacy_max_llm_calls": getattr(module, "MAX_LLM_CALLS", None)}
            )
            result["model_sha256"] = digest((folder / "starnet_model.py").read_bytes())
            result["llm_model"] = os.getenv("SMP_LLM_MODEL", DEFAULT_MODEL)
            for step in range(1, 121):
                status = model.step()
                if step % 10 == 0:
                    write_json(result_path.with_suffix(".progress.json"), {
                        "archive": archive.name, "family": job["family"], "steps": step,
                        "llm_calls": llm.attempts, "budget": env.get_remaining_budget(),
                    })
                if status or env.get_remaining_budget() < 0.5 or llm.attempts >= 120:
                    break
            controller = model.controller
            if llm.blocked_calls and not job.get("allow_offline_fallback", False):
                raise RuntimeError("archive requires LLM; offline result is not a faithful run")
            result.update({
                "status": "completed", "score": env.evaluate(), "steps": step,
                "actions": {kind: sum(call[0] == kind for call in env.calls)
                            for kind in ("scan", "comm", "cut", "shield")},
                "action_failures": controller.action_failures,
                "llm_calls": llm.attempts, "llm_transport_errors": llm.errors,
                "forced_llm_failures": llm.blocked_calls,
                "llm_mode": "forced_offline_failure" if llm.blocked_calls else (
                    "real" if llm.attempts else "not_requested_by_archive"
                ),
                "llm_accepted": getattr(controller, "llm_accepted", None),
                "llm_fallbacks": getattr(controller, "llm_fallbacks", None),
                "remaining_budget": env.get_remaining_budget(),
                "stop_reason": str(controller.stop_reason),
                "actions_sha256": digest(json.dumps(env.calls).encode()),
            })
    except Exception as exc:
        result.update({"status": "error", "error_type": type(exc).__name__})
    finally:
        os.chdir(previous_cwd)
    result["elapsed_seconds"] = time.monotonic() - started
    write_json(result_path, result)
    return 0 if result["status"] == "completed" else 1


def run_job(job_path: Path) -> dict:
    job = json.loads(job_path.read_text())
    result_path = Path(job["result_path"])
    if result_path.exists():
        previous = json.loads(result_path.read_text())
        if (previous.get("status") == "completed"
                and previous.get("runner_sha256") == digest(Path(__file__).read_bytes())
                and previous.get("offline_only") == job.get("offline_only", False)
                and previous.get("allow_offline_fallback") == job.get("allow_offline_fallback", False)
                and previous.get("archive_sha256") == digest(Path(job["archive"]).read_bytes())):
            return previous
    process = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(job_path)],
        cwd=ROOT, capture_output=True, text=True, timeout=2400,
    )
    if not result_path.exists():
        raise RuntimeError(f"archive worker exited {process.returncode} without a result")
    return json.loads(result_path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--allow-offline-fallback", action="store_true")
    parser.add_argument("--families", nargs="+", choices=tuple(SEED_SPECS), default=list(SEED_SPECS))
    parser.add_argument("--archives", nargs="+", choices=tuple(OFFICIAL), default=list(OFFICIAL))
    parser.add_argument("--result-dir", type=Path, default=ROOT / "experiments/raw/archive-comparison-20260912")
    parser.add_argument("--output", type=Path, default=ROOT / "experiments/reports/archive-score-comparison-20260912.json")
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker)
    if args.workers <= 0 or args.timeout <= 0:
        parser.error("workers and timeout must be positive")
    if args.allow_offline_fallback and not args.offline_only:
        parser.error("--allow-offline-fallback requires --offline-only")
    jobs = []
    for name in args.archives:
        archive = ROOT / "artifacts/submission" / name
        if not archive.is_file():
            raise FileNotFoundError(name)
        for family in args.families:
            stem = f"{archive.stem}--{family}"
            path = args.result_dir.resolve() / f"{stem}.job.json"
            write_json(path, {"archive": str(archive), "family": family, "timeout": args.timeout,
                              "offline_only": args.offline_only,
                              "allow_offline_fallback": args.allow_offline_fallback,
                              "result_path": str(path.with_name(stem + ".result.json"))})
            jobs.append(path)
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run_job, job) for job in jobs]):
            row = future.result()
            rows.append(row)
            print(json.dumps({k: row.get(k) for k in ("archive", "family", "status", "score", "llm_calls")}), flush=True)
    summaries = []
    for name in args.archives:
        selected = [row for row in rows if row["archive"] == name]
        complete = all(row["status"] == "completed" for row in selected)
        summaries.append({
            "archive": name, "official_score": OFFICIAL[name], "complete": complete,
            "local_mean": statistics.mean(row["score"] for row in selected) if complete else None,
            "local_min": min(row["score"] for row in selected) if complete else None,
            "local_max": max(row["score"] for row in selected) if complete else None,
            "llm_calls": sum(row.get("llm_calls", 0) for row in selected),
            "llm_transport_errors": sum(row.get("llm_transport_errors", 0) for row in selected),
            "forced_llm_failures": sum(row.get("forced_llm_failures", 0) for row in selected),
            "action_failures": sum(row.get("action_failures", 0) for row in selected),
        })
    write_json(args.output, {"schema_version": 1, "families": args.families,
                            "node_count": 50, "budget": 100, "repetition": 1,
                            "llm_mode": ("offline_forced_failure" if args.allow_offline_fallback else
                                         "offline_original_no_llm" if args.offline_only else
                                         "real_if_requested_by_unchanged_archive"),
                            "rows": rows, "summary": summaries})
    return 0 if all(item["complete"] for item in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())

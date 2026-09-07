#!/usr/bin/env python3
"""Run one resumable experiment session per child process.

The structural planner can legitimately touch many graph states.  On the
4-GiB runner, a fresh child per session is safer than relying on Python's
allocator to return memory after a completed remote session.  The child is
the existing public experiment runner; this wrapper only provides bounded
process isolation and resumability.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _count_main_rows(sessions_dir: Path) -> int:
    if not sessions_dir.is_dir():
        return 0
    count = 0
    for path in sessions_dir.glob("main-*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("phase") == "main":
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--experimental-calibration-report", type=Path)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--max-sessions", type=int)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--worker-index", type=int, default=0)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    expected = len(manifest["main_seeds"]) * len(manifest["variants"]) * int(manifest["main_repetitions"])
    child = [
        sys.executable,
        "scripts/run_experiments.py",
        "--manifest", str(args.manifest),
        "--result-dir", str(args.result_dir),
        "--skip-preflight",
        "--resume",
        "--max-new-sessions", "1",
        "--main-worker-count", str(args.worker_count),
        "--main-worker-index", str(args.worker_index),
    ]
    if args.experimental_calibration_report is not None:
        child.extend(["--experimental-calibration-report", str(args.experimental_calibration_report)])
    if args.timeout is not None:
        child.extend(["--timeout", str(args.timeout)])

    # Importing after argument parsing keeps this wrapper usable by the
    # documented ``python scripts/...`` invocation as well as module tests.
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.run_experiments import result_namespace

    plan_dir = result_namespace(args.result_dir.resolve(), manifest)
    launched = 0
    while True:
        gate_status = plan_dir / "gate_status.json"
        gate_complete = False
        if gate_status.is_file():
            gate_complete = bool(json.loads(gate_status.read_text(encoding="utf-8")).get("gate_complete"))
        branch = "stable"
        completed = _count_main_rows(plan_dir / branch / "sessions")
        if gate_complete and completed >= expected:
            print(f"complete main_sessions={completed}/{expected} plan_dir={plan_dir}", flush=True)
            return 0
        if args.max_sessions is not None and launched >= args.max_sessions:
            print(f"paused child_sessions={launched} main_sessions={completed}/{expected} plan_dir={plan_dir}", flush=True)
            return 0
        completed_run = subprocess.run(child, cwd=PROJECT_ROOT, check=False)
        launched += 1
        if completed_run.returncode != 0:
            print(f"child failed returncode={completed_run.returncode} after={launched}", file=sys.stderr, flush=True)
            return completed_run.returncode


if __name__ == "__main__":
    raise SystemExit(main())

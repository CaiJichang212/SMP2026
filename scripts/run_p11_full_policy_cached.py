#!/usr/bin/env python3
"""Grouped P11 runner with exact, explicitly marked reference reuse."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.analyze_p11_full_policy_validation import topology_block
from scripts.p11_reference_cache import reuse_known_best_result, reuse_prompt1_result
from scripts.run_p11_full_policy_validation import (
    PROTOCOL, P9_ARCHIVE, digest, json_digest, metric, run_archive, run_source,
    source_snapshot, write_json,
)
from starnet.experiments.p11_validation_seeds import confirmation_cases, development_cases


CACHE_HELPER = ROOT / "scripts/p11_reference_cache.py"
BASE_RUNNER = ROOT / "scripts/run_p11_full_policy_validation.py"


def _fresh(result, case_id):
    result["reference_cache"] = {"kind": "fresh_execution", "source_case_id": case_id}
    return result


def run_group(job):
    group_cases, expected_snapshot = job
    if source_snapshot() != expected_snapshot:
        raise RuntimeError("P11 source changed before cached group")
    prompt1_cache = {}
    magnitude_cache = {}
    known_cache = {}
    rows = []
    for case_id, amplitude, values, seed in group_cases:
        best = max(values)
        best_ids = tuple(index for index, value in enumerate(values, 1) if value == best)
        prompt1 = float(values[0])
        p11 = run_source(seed, "p11")
        p11["reference_cache"] = {"kind": "not_cacheable_p11_execution",
                                  "source_case_id": case_id}

        if prompt1 not in prompt1_cache:
            p9 = _fresh(run_archive(seed), case_id)
            prompt1_cache[prompt1] = (case_id, seed, p9)
        else:
            source_id, source_seed, source_result = prompt1_cache[prompt1]
            p9 = reuse_prompt1_result(source_result, source_seed, seed,
                                      source_case_id=source_id)

        if prompt1 not in magnitude_cache:
            magnitude = _fresh(run_source(seed, "fixed1_online_magnitude_no_probe"), case_id)
            magnitude_cache[prompt1] = (case_id, seed, magnitude)
        else:
            source_id, source_seed, source_result = magnitude_cache[prompt1]
            magnitude = reuse_prompt1_result(source_result, source_seed, seed,
                                              source_case_id=source_id)

        if best not in known_cache:
            known = _fresh(run_archive(seed, known_prompt_id=best_ids[0]), case_id)
            known_cache[best] = (case_id, seed, best_ids[0], known)
        else:
            source_id, source_seed, source_prompt, source_result = known_cache[best]
            known = reuse_known_best_result(
                source_result, source_seed, seed, source_prompt_id=source_prompt,
                target_prompt_id=best_ids[0], source_case_id=source_id,
            )
        arms = {"p11": p11, "p9_no_probe": p9,
                "known_best_id_p9_reference": known,
                "fixed1_online_magnitude_no_probe": magnitude}
        rows.append({"case_id": case_id, "amplitude": amplitude,
                     "topology_block": topology_block(case_id),
                     "prompt_values": list(values), "best_prompt_ids": list(best_ids),
                     "prompt1_best": 1 in best_ids, "seed_sha256": json_digest(seed),
                     "arms": arms,
                     "paired": {"p11_vs_p9": p11["score"] - p9["score"],
                        "p11_signed_gap_to_known_id": known["score"] - p11["score"],
                        "p9_signed_gap_to_known_id": known["score"] - p9["score"],
                        "magnitude_vs_p9": magnitude["score"] - p9["score"]},
                     "identified_best": p11["p11_selected_prompt_id"] in best_ids})
    if source_snapshot() != expected_snapshot:
        raise RuntimeError("P11 source changed during cached group")
    return rows


def grouped(cases):
    groups = {}
    for case in cases:
        case_id, amplitude, _, _ = case
        groups.setdefault((topology_block(case_id), amplitude), []).append(case)
    return [groups[key] for key in sorted(groups)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=("development", "confirmation"), default="development")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--checkpoint-every", type=int, default=2)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.cohort == "confirmation" and not args.confirm:
        parser.error("fresh P11 confirmation remains closed")
    if args.cohort == "development" and args.confirm:
        parser.error("--confirm is valid only for confirmation")
    cases = list(development_cases() if args.cohort == "development"
                 else confirmation_cases(allow_confirmation=True))
    snapshot = source_snapshot()
    config = {"protocol_sha256": digest(PROTOCOL), "runner_sha256": digest(Path(__file__)),
              "base_runner_sha256": digest(BASE_RUNNER),
              "reference_cache_sha256": digest(CACHE_HELPER),
              "seed_source_sha256": digest(ROOT / "src/starnet/experiments/p11_validation_seeds.py"),
              "ledger_sha256": digest(ROOT / "src/starnet/policy/prompt_calibration_experiment.py"),
              "source_snapshot": snapshot, "p9_archive_sha256": digest(P9_ARCHIVE),
              "cohort": args.cohort, "cases": len(cases), "workers": args.workers,
              "confirmation_opened": args.cohort == "confirmation",
              "reference_reuse": "explicit exact group cache; P11 always fresh"}
    progress = args.raw_output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("cached P11 progress identity mismatch")
        rows = list(saved["rows"])
    completed = {row["case_id"] for row in rows}
    jobs = [(tuple(case for case in group if case[0] not in completed), snapshot)
            for group in grouped(cases)]
    jobs = [job for job in jobs if job[0]]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        iterator = iter(jobs)
        futures = {}
        for _ in range(args.workers):
            job = next(iterator, None)
            if job:
                futures[pool.submit(run_group, job)] = job[0][0][0]
        try:
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    group_id = futures.pop(future)
                    rows.extend(future.result())
                    if len(rows) % (6 * args.checkpoint_every) == 0:
                        write_json(progress, {"config": config, "rows": rows})
                    print(json.dumps({"group": group_id, "completed": len(rows)},
                                     ensure_ascii=False), flush=True)
                    job = next(iterator, None)
                    if job:
                        futures[pool.submit(run_group, job)] = job[0][0][0]
        except Exception as exc:
            for pending in futures:
                pending.cancel()
            write_json(progress, {"config": config, "rows": rows,
                                  "error": {"group": group_id, "type": type(exc).__name__}})
            raise
    write_json(progress, {"config": config, "rows": rows})
    raw = {"config": config, "complete": len(rows) == len(cases), "rows": rows}
    write_json(args.raw_output, raw)
    compact = {"config": config, "complete": raw["complete"],
               "summary": {key: metric(rows, key) for key in (
                   "p11_vs_p9", "p11_signed_gap_to_known_id",
                   "p9_signed_gap_to_known_id", "magnitude_vs_p9")},
               "reference_reuse_counts": {
                   kind: sum(result["reference_cache"]["kind"] == kind
                             for row in rows for result in row["arms"].values())
                   for kind in ("fresh_execution", "identical_prompt1_execution",
                                "equal_strength_known_id_relabel",
                                "not_cacheable_p11_execution")},
               "raw_log": {"path": str(args.raw_output.resolve().relative_to(ROOT)),
                           "sha256": digest(args.raw_output), "committed": False},
               "production_enabled": False, "platform_score": None}
    write_json(args.output, compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

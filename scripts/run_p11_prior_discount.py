#!/usr/bin/env python3
"""Compare frozen P11 with a development-only unknown-node prior discount."""

from __future__ import annotations

import argparse
import copy
import itertools
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_submission_archives import CountingLLM
from scripts.run_p11_full_policy_validation import digest, json_digest, run_model
from scripts.run_p9_distribution_validation import LoggedEnvironment
from starnet.experiments.seeds import SEED_SPECS, seed_payload
from starnet.runtime.p11_prior_discount_experiment import (
    DiscountedPromptLearningRuntimeController,
)
from starnet.runtime.p11_prompt_controller_experiment import (
    PromptLearningRuntimeController,
)
from starnet.runtime.stage import ContestStage
from starnet.submission.starnet_model import ParticipantSquadModel


PROTOCOL = ROOT / "experiments/manifests/p11-prior-discount-development-20260914.json"
SOURCE_FILES = (
    ROOT / "src/starnet/runtime/p11_prompt_controller_experiment.py",
    ROOT / "src/starnet/runtime/p11_prior_discount_experiment.py",
)
BASE_VALUES = (15.0, 10.0, -5.0)


def source_snapshot() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): digest(path) for path in SOURCE_FILES}


def run_arm(seed: dict, *, discounted: bool) -> dict:
    env = LoggedEnvironment(seed)
    llm = CountingLLM(1.0, offline_only=True)
    people = json.loads((ROOT / "src/starnet/submission/config.json").read_text())["person"]
    model = ParticipantSquadModel(env, people, llm)
    controller_type = (
        DiscountedPromptLearningRuntimeController
        if discounted else PromptLearningRuntimeController
    )
    model.controller = controller_type(
        env,
        llm_ranker=lambda payload: None,
        stage=ContestStage.PRELIMINARY,
        config=model.controller.config,
        p8_mode="conservative",
        require_stage_envelope=True,
    )
    result = run_model(model, env)
    controller = model.controller
    result.update({
        "execution": "discounted_p11" if discounted else "original_p11",
        "p11_empirical_prompt_prior": getattr(
            controller, "p11_empirical_prompt_prior", None,
        ),
        "p11_discounted_prompt_prior": getattr(
            controller, "p11_discounted_prompt_prior", None,
        ),
        "p11_prior_discount": getattr(controller, "p11_prior_discount", 1.0),
        "p11_prior_predictions": getattr(controller, "p11_prior_predictions", 0),
    })
    return result


def paired_summary(rows: list[dict]) -> dict:
    gains = [row["paired_gain"] for row in rows]
    family_means = {
        family: statistics.fmean(
            row["paired_gain"] for row in rows if row["family"] == family
        )
        for family in SEED_SPECS
    }
    prompt1 = [row["paired_gain"] for row in rows if row["prompt1_best"]]
    return {
        "cases": len(gains),
        "mean": statistics.fmean(gains),
        "minimum": min(gains),
        "maximum": max(gains),
        "win_tie_loss": [
            sum(value > 1e-8 for value in gains),
            sum(abs(value) <= 1e-8 for value in gains),
            sum(value < -1e-8 for value in gains),
        ],
        "prompt1_best_mean": statistics.fmean(prompt1),
        "family_means": family_means,
        "nonnegative_family_means": sum(value >= 0.0 for value in family_means.values()),
    }


def evaluate_gate(summary: dict) -> dict:
    checks = {
        "paired_mean_gt_1": summary["mean"] > 1.0,
        "prompt1_best_mean_gt_0": summary["prompt1_best_mean"] > 0.0,
        "at_least_four_nonnegative_family_means": (
            summary["nonnegative_family_means"] >= 4
        ),
        "worst_pair_at_least_minus_10": summary["minimum"] >= -10.0,
    }
    return {"checks": checks, "passed": all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = source_snapshot()
    config = {
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "source_snapshot": snapshot,
        "families": list(SEED_SPECS),
        "prompt_values": list(BASE_VALUES),
        "cases": len(SEED_SPECS) * 6,
        "workers": 1,
    }
    progress = args.output.with_suffix(".progress.json")
    rows = []
    if progress.exists():
        saved = json.loads(progress.read_text())
        if saved.get("config") != config:
            parser.error("P11 prior-discount progress identity mismatch")
        rows = list(saved.get("rows", []))
    completed = {row["case_id"] for row in rows}
    for family in SEED_SPECS:
        for values in itertools.permutations(BASE_VALUES):
            case_id = f"{family}:1:{'_'.join(str(value) for value in values)}"
            if case_id in completed:
                continue
            seed = copy.deepcopy(seed_payload(family, 50, 1))
            seed["prompts"] = {str(index): value for index, value in enumerate(values, 1)}
            original = run_arm(seed, discounted=False)
            discounted = run_arm(seed, discounted=True)
            if source_snapshot() != snapshot:
                raise RuntimeError("P11 prior-discount source changed during run")
            if (original["p11_selected_prompt_id"] != discounted["p11_selected_prompt_id"]
                    or original["p11_probe_budget"] != discounted["p11_probe_budget"]):
                raise RuntimeError("P11 calibration invariant changed")
            row = {
                "case_id": case_id,
                "family": family,
                "prompt_values": list(values),
                "prompt1_best": values[0] == max(values),
                "seed_sha256": json_digest(seed),
                "paired_gain": discounted["score"] - original["score"],
                "arms": {"original_p11": original, "discounted_p11": discounted},
            }
            rows.append(row)
            completed.add(case_id)
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps(
                {"config": config, "rows": rows}, ensure_ascii=False, indent=2,
            ) + "\n")
            print(json.dumps({"case_id": case_id, "completed": len(rows),
                              "paired_gain": row["paired_gain"]}), flush=True)
    if len(rows) != config["cases"]:
        raise ValueError("P11 prior-discount cohort incomplete")
    summary = paired_summary(rows)
    report = {
        "config": config,
        "complete": True,
        "comparison": summary,
        "development_gate": evaluate_gate(summary),
        "rows": rows,
        "changes_runtime_selection": False,
        "production_enabled": False,
        "platform_score": None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"comparison": summary, "gate": report["development_gate"]}),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

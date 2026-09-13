#!/usr/bin/env python3
"""Run the preregistered expected-clipped prior development screen."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.run_local_policy_matrix import LocalPublicEnvironment
from scripts.run_p8_search import run_p8, seed_hash
from starnet.experiments.p9_distribution_seeds import seed_payload
from starnet.policy.p9_expected_clip_experiment import choose_expected_clip_action


FAMILIES = ("er_resampled", "ba_resampled", "ws_resampled", "sbm_resampled")
SHIFTS = ("near_upper_bound", "saturated_hubs")


def _run(seed, variant):
    environments = []

    def factory(payload):
        env = LocalPublicEnvironment(payload)
        environments.append(env)
        return env

    if variant == "bounded_p8":
        result = run_p8(seed, "conservative", env_factory=factory)
    else:
        with patch("scripts.run_p8_search.choose_p8_action", new=choose_expected_clip_action):
            result = run_p8(seed, "conservative", env_factory=factory)
    result["action_sequence"] = environments[0].calls
    result["actions_sha256"] = hashlib.sha256(
        json.dumps(environments[0].calls).encode()
    ).hexdigest()
    return result


def _signature(action):
    return tuple(action)


def _action_delta(candidate, control):
    candidate_actions = candidate["action_sequence"][50:]
    control_actions = control["action_sequence"][50:]
    changed_positions = sum(
        left != right for left, right in zip(candidate_actions, control_actions)
    ) + abs(len(candidate_actions) - len(control_actions))
    width = max(len(candidate_actions), len(control_actions))
    first = next((index for index in range(width) if
                  (candidate_actions[index] if index < len(candidate_actions) else None) !=
                  (control_actions[index] if index < len(control_actions) else None)), None)
    candidate_count, control_count = Counter(map(_signature, candidate_actions)), Counter(map(_signature, control_actions))
    return {
        "changed_intervention_positions": changed_positions,
        "first_divergence_intervention": None if first is None else first + 1,
        "additional_actions": [{"action": list(action), "count": count}
                               for action, count in sorted((candidate_count - control_count).items())],
        "missing_actions": [{"action": list(action), "count": count}
                            for action, count in sorted((control_count - candidate_count).items())],
    }


def main() -> int:
    output = ROOT / "experiments/reports/p9-expected-clip-dev901-20260913.json"
    rows = []
    for family in FAMILIES:
        for shift in SHIFTS:
            seed = seed_payload(family, 901, shift)
            control = _run(seed, "bounded_p8")
            candidate = _run(seed, "expected_clip")
            row = {
                "family": family,
                "repetition": 901,
                "shift_stratum": shift,
                "seed_sha256": seed_hash(seed),
                "bounded_p8": control,
                "expected_clip": candidate,
                "score_delta": candidate["score"] - control["score"],
                "action_delta": _action_delta(candidate, control),
            }
            rows.append(row)
            output.write_text(json.dumps({"complete": False, "rows": rows}, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({
                "family": family, "shift": shift, "delta": row["score_delta"],
                "changed": row["action_delta"]["changed_intervention_positions"],
            }), flush=True)
    values = [row["score_delta"] for row in rows]
    report = {
        "schema_version": 1,
        "purpose": "Consumed development screen of expected clipped untried prior; not validation or promotion evidence.",
        "confirmation_opened": False,
        "workers": 1,
        "families": list(FAMILIES),
        "shifts": list(SHIFTS),
        "repetitions": [901],
        "policy_sha256": hashlib.sha256((ROOT / "src/starnet/policy/p9_expected_clip_experiment.py").read_bytes()).hexdigest(),
        "p8_policy_sha256": hashlib.sha256((ROOT / "src/starnet/policy/p8_experiment.py").read_bytes()).hexdigest(),
        "complete": True,
        "rows": rows,
        "summary": {
            "cases": len(rows),
            "mean_delta": statistics.fmean(values),
            "minimum_delta": min(values),
            "maximum_delta": max(values),
            "win_tie_loss": [sum(value > 1e-8 for value in values),
                             sum(abs(value) <= 1e-8 for value in values),
                             sum(value < -1e-8 for value in values)],
            "changed_cases": sum(row["action_delta"]["changed_intervention_positions"] > 0 for row in rows),
            "changed_intervention_positions": sum(row["action_delta"]["changed_intervention_positions"] for row in rows),
        },
        "production_promotion_allowed": False,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

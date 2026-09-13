#!/usr/bin/env python3
"""Small public-API mechanism probe, not a 50-node release qualification."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_p7_remote_probe import PairedEnvironment
from scripts.run_p8_search import run_p8, seed_hash
from starnet.policy.p9_coverage_experiment import choose_coverage_action


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", default="http://8.222.218.162:5000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seed = {"global_setting": {"max_budget": 4.5, "max_api_calls": 120},
            "nodes": [{"id": node, "w": weight, "persona": "和平", "comm_left": 3, "r": 1.5}
                      for node, weight in ((1, 100.0), (2, 1.0), (3, 1.0))],
            "edges": [[1, 2], [1, 3], [2, 3]], "original_total": 102.0,
            "prompts": {"1": 15.0, "2": 10.0, "3": -5.0}}
    report = {"purpose": "probe positive-to-positive cut excluded by P8's graph gate",
              "not_release_qualification": True, "platform_score": None,
              "seed_sha256": seed_hash(seed),
              "precomputed_prediction": {"p8": 124.5, "coverage": 912.0 / 7,
                                         "difference": 912.0 / 7 - 124.5}, "rows": []}
    for name in ("p8", "coverage"):
        env = PairedEnvironment(seed, args.server_url, 20)
        if name == "p8":
            result = run_p8(seed, "conservative", env_factory=lambda _: env)
        else:
            with patch("scripts.run_p8_search.choose_p8_action", choose_coverage_action):
                result = run_p8(seed, "conservative", env_factory=lambda _: env)
        report["rows"].append({"variant": name, "result": result,
                               "local_replay_score": env.local_score,
                               "response_error": env.response_error})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report["rows"][-1]), flush=True)


if __name__ == "__main__":
    main()

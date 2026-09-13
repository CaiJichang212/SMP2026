#!/usr/bin/env python3
"""Collect public communication returns around opinion saturation bounds."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from SMP_Starter_Kit.api_client import RemoteStarNetEnv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--server-url", default="http://8.222.218.162:5000")
    args = parser.parse_args()
    weights = (-110., -100., -99., -90., 0., 90., 99., 100., 110.)
    report = {"hypotheses": ["unbounded additive response", "clip each communication to [-100,100]"],
              "public_custom_seed_mechanism_probe": True, "platform_score": None,
              "runs": [], "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for factor in (0.2, 1.5):
        for prompt_id, strength in ((1, 15.0), (3, -5.0)):
            seed = {"global_setting": {"max_budget": 100., "max_api_calls": 120},
                    "nodes": [{"id": index, "w": w, "persona": "和平", "r": factor, "comm_left": 3}
                              for index, w in enumerate(weights, 1)],
                    "edges": [], "original_total": sum(weights),
                    "prompts": {"1": 15., "2": 10., "3": -5.}}
            env = RemoteStarNetEnv(args.server_url, seed, timeout=20)
            run = {"factor": factor, "prompt_id": prompt_id,
                   "seed_sha256": hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest(),
                   "observations": []}
            report["runs"].append(run)
            for node, initial_w in enumerate(weights, 1):
                scan = env.scan_node(node)
                previous = float(scan["w"])
                for turn in (1, 2, 3):
                    response = env.communicate(node, prompt_id)
                    unbounded = previous + strength * factor * 0.5 ** (turn - 1)
                    bounded = max(-100., min(100., unbounded))
                    observed = float(response["new_w"])
                    run["observations"].append({"node": node, "initial_w": initial_w,
                                                "scanned_w": scan["w"], "turn": turn,
                                                "previous_w": previous, "response": response,
                                                "unbounded_prediction": unbounded,
                                                "bounded_prediction": bounded,
                                                "unbounded_error": observed - unbounded,
                                                "bounded_error": observed - bounded})
                    previous = observed
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"factor": factor, "prompt_id": prompt_id,
                              "max_unbounded_error": max(abs(x["unbounded_error"]) for x in run["observations"]),
                              "max_bounded_error": max(abs(x["bounded_error"]) for x in run["observations"])}), flush=True)


if __name__ == "__main__":
    main()

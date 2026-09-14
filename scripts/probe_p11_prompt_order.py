#!/usr/bin/env python3
"""Verify node-level diminishing returns across different public prompt IDs."""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from SMP_Starter_Kit.api_client import RemoteStarNetEnv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    orders = list(itertools.permutations((1, 2, 3)))
    values = {1: 15.0, 2: 10.0, 3: -5.0}
    seed = {"global_setting": {"max_budget": 100.0, "max_api_calls": 120},
            "nodes": [{"id": index, "w": 0.0, "persona": "和平", "r": factor, "comm_left": 3}
                      for index, factor in enumerate((0.2, 1.0, 1.5, 0.2, 1.0, 1.5), 1)],
            "edges": [], "original_total": 0.0,
            "prompts": {str(key): value for key, value in values.items()}}
    env = RemoteStarNetEnv("http://8.222.218.162:5000", seed, timeout=20)
    rows = []
    for node, order in enumerate(orders, 1):
        public = env.scan_node(node)
        previous = public["w"]
        for turn, prompt_id in enumerate(order, 1):
            response = env.communicate(node, prompt_id)
            delta = response["new_w"] - previous
            normalized = delta / (0.5 ** (turn - 1))
            # Ground truth is used only by this measurement script, never
            # by a submission or a prompt-learning policy.
            expected = values[prompt_id] * seed["nodes"][node - 1]["r"]
            rows.append({"node": node, "order": order, "turn": turn, "prompt_id": prompt_id,
                         "before": previous, "response": response,
                         "normalized_delta": normalized, "expected_for_probe": expected,
                         "error": normalized - expected})
            previous = response["new_w"]
    report = {"purpose": "public custom-seed mechanism check, not hidden official values",
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "rows": rows, "max_error": max(abs(row["error"]) for row in rows),
              "passed": all(abs(row["error"]) < 1e-8 for row in rows)}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"observations": len(rows), "max_error": report["max_error"], "passed": report["passed"]}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Observe only documented public fields in the sandbox's default scenario."""
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
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    report = {"purpose": "public default-sandbox distribution diagnostic; not hidden official evaluation",
              "selection": "scan documented preliminary IDs 1..50; up to two non-saturated IDs per persona, sorted by ID",
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "rows": []}
    for repetition in range(args.repetitions):
        env = RemoteStarNetEnv("http://8.222.218.162:5000", timeout=20)
        row = {"repetition": repetition, "initial_budget": env.get_remaining_budget(), "nodes": {}, "responses": []}
        report["rows"].append(row)
        for node in range(1, 51):
            if env.get_remaining_budget() < 0.5:
                break
            response = env.scan_node(node)
            if response is not None:
                row["nodes"][node] = {key: response.get(key) for key in ("w", "persona", "comm_left", "neighbors")}
        for persona in ("和平", "中立", "暴力"):
            choices = [node for node, data in row["nodes"].items()
                       if data["persona"] == persona and -70 <= data["w"] <= 70 and data["comm_left"] == 3][:2]
            for node in choices:
                if env.get_remaining_budget() < 2:
                    break
                result = env.communicate(node, 1)
                row["responses"].append({"node": node, "persona": persona, "old_w": row["nodes"][node]["w"],
                                         "new_w": result.get("new_w"), "status": result.get("status")})
        row["remaining_budget"] = env.get_remaining_budget()
        row["public_graph_sha256"] = hashlib.sha256(json.dumps(row["nodes"], sort_keys=True).encode()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"repetition": repetition, "budget": row["initial_budget"], "nodes": len(row["nodes"]),
                          "responses": row["responses"], "graph_sha": row["public_graph_sha256"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

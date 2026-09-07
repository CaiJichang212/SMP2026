#!/usr/bin/env python3
"""Rebuild aggregate JSONL/CSV files from atomic session records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.sessions.glob("*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    args.sessions.parent.joinpath("results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    columns = ["session_id", "phase", "seed_id", "variant", "repetition", "final_score", "comparable", "step_count", "llm_calls", "remaining_budget", "action_failures", "elapsed_seconds"]
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(json.dumps(row.get(column, ""), ensure_ascii=False) for column in columns))
    args.sessions.parent.joinpath("results.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"rebuilt rows={len(rows)} root={args.sessions.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

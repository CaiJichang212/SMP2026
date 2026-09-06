#!/usr/bin/env python3
"""Analyze P2.2 without letting historical response rows leak topology labels.

P1 response measurements are intentionally reused verbatim.  P2.2 settlement
rows come solely from its new topology-disjoint manifest.  The submission
never imports this offline tool or calls final evaluation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from calibrate_v1 import build_report, load_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--p1-results", type=Path, required=True)
    parser.add_argument("--p2-results", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("manifest root must be an object")
    p1_rows = [row for row in load_jsonl(args.p1_results) if row.get("kind") == "response"]
    p2_rows = [row for row in load_jsonl(args.p2_results) if row.get("kind") == "settlement"]
    report: dict[str, Any] = build_report(manifest, p1_rows + p2_rows)
    report["provenance"] = {
        "p1_response_rows": len(p1_rows),
        "p2_settlement_rows": len(p2_rows),
        "response_source": str(args.p1_results),
        "settlement_source": str(args.p2_results),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"gate_passed={report['gate_passed']} report={args.report}")
    return 0 if report["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

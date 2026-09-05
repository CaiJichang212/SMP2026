"""Regression checks for the fail-closed V1 local-probe report."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.analyze_v1_local_probes import canonical_hash, summarize


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AnalyzeV1LocalProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(
            (PROJECT_ROOT / "experiments" / "manifests" / "v1-local-probes.json").read_text(encoding="utf-8")
        )

    def _row(self, probe_id: str, *, comparable: bool = True) -> dict[str, object]:
        return {
            "probe_id": probe_id,
            "plan_hash": canonical_hash(self.manifest),
            "comparable": comparable,
            "protocol_error": None if comparable else "RemoteProtocolError",
            "action_failures": 0,
            "scan_snapshot_match": comparable,
            "final_score": 1.0 if comparable else None,
        }

    def test_requires_a_complete_comparable_manifest_cohort(self) -> None:
        rows = [self._row(str(probe["id"])) for probe in self.manifest["probes"]]
        summary = summarize(self.manifest, rows)
        self.assertEqual(summary["analysis_status"], "complete")
        self.assertEqual(summary["comparable_probe_count"], 10)

    def test_protocol_error_is_excluded_even_if_other_rows_are_valid(self) -> None:
        rows = [self._row(str(probe["id"])) for probe in self.manifest["probes"]]
        rows[0] = self._row(str(self.manifest["probes"][0]["id"]), comparable=False)
        summary = summarize(self.manifest, rows)
        self.assertEqual(summary["analysis_status"], "insufficient_noncomparable_data")
        self.assertEqual(summary["comparable_probe_count"], 9)
        self.assertEqual(summary["protocol_error_counts"], {"RemoteProtocolError": 1})


if __name__ == "__main__":
    unittest.main()

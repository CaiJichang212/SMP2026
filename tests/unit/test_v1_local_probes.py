"""Offline regression checks for resumable V1 local mechanism probes."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.run_v1_local_probes import canonical_hash, completed_probe


class V1LocalProbeTests(unittest.TestCase):
    def test_resume_requires_matching_probe_or_legacy_seed_and_actions(self) -> None:
        probe = {
            "id": "probe",
            "seed": {"nodes": [{"id": 1}], "edges": []},
            "actions": [{"kind": "shield", "target_node_1": 1}],
        }
        plan_hash = canonical_hash({"name": "plan"})
        probe_hash = canonical_hash(probe)
        seed_hash = canonical_hash(probe["seed"])
        actions_hash = canonical_hash(probe["actions"])

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "probe-r1.json"
            path.write_text(
                json.dumps(
                    {
                        "plan_hash": plan_hash,
                        "probe_hash": probe_hash,
                        "completed_at": "2026-09-04T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                completed_probe(
                    path,
                    plan_hash=plan_hash,
                    probe_hash=probe_hash,
                    seed_payload_hash=seed_hash,
                    actions_hash=actions_hash,
                )
            )

            path.write_text(
                json.dumps(
                    {
                        "plan_hash": plan_hash,
                        "seed_payload_hash": seed_hash,
                        "actions": probe["actions"],
                        "completed_at": "2026-09-04T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                completed_probe(
                    path,
                    plan_hash=plan_hash,
                    probe_hash=probe_hash,
                    seed_payload_hash=seed_hash,
                    actions_hash=actions_hash,
                )
            )
            self.assertFalse(
                completed_probe(
                    path,
                    plan_hash=plan_hash,
                    probe_hash=probe_hash,
                    seed_payload_hash=seed_hash,
                    actions_hash=canonical_hash([]),
                )
            )


if __name__ == "__main__":
    unittest.main()

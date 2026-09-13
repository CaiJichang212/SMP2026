"""A statistical pass must never accidentally authorize an untested entry."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_submission
from scripts.seal_p9_bounded_release import (
    PROTOCOL, expected_runtime_paths, seal, seed_sha, sha,
)
from scripts.verify_p9_release_archive import (
    load_current_seal, qualification_structure, require_unique_members,
)
from starnet.policy import p8_qualification
from starnet.experiments.p9_distribution_seeds import seed_payload


class BoundedBuildSealTests(unittest.TestCase):
    def test_mean_pass_without_entry_seal_cannot_build(self):
        with tempfile.TemporaryDirectory(prefix="p9-build-seal-") as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "config.json").write_text(json.dumps({"person": [
                {"role": "CommanderAgent", "experimental_p8_mode": "conservative"}
            ]}))
            report = root / "report.json"
            report.write_text(json.dumps({
                "variants": {"conservative": {"mean_score_gate_passed": True}},
                "release_gate_pending": "real entry validation",
            }))
            with patch.object(build_submission, "PROJECT_ROOT", root), \
                 patch.object(build_submission, "SOURCE_DIR", source), \
                 patch.object(p8_qualification, "P8_GATE_REPORT_RELATIVE_PATH", "report.json"), \
                 patch.object(p8_qualification, "P8_GATE_REPORT_SHA256", hashlib.sha256(report.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(SystemExit, "最终入口验证"):
                    build_submission.verify_p8_release()

    def test_confirmation_report_cannot_bypass_seal_by_omitting_pending_key(self):
        with tempfile.TemporaryDirectory(prefix="p9-build-seal-") as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "config.json").write_text(json.dumps({"person": [
                {"role": "CommanderAgent", "experimental_p8_mode": "conservative"}
            ]}))
            report = root / "report.json"
            report.write_text(json.dumps({
                "cohort": "confirmation",
                "variants": {"conservative": {"mean_score_gate_passed": True}},
            }))
            with patch.object(build_submission, "PROJECT_ROOT", root), \
                 patch.object(build_submission, "SOURCE_DIR", source), \
                 patch.object(p8_qualification, "P8_GATE_REPORT_RELATIVE_PATH", "report.json"), \
                 patch.object(p8_qualification, "P8_GATE_REPORT_SHA256", hashlib.sha256(report.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(SystemExit, "最终入口验证"):
                    build_submission.verify_p8_release()

    def test_qualification_allows_only_literal_metadata_changes(self):
        historical = (Path(__file__).resolve().parents[2]
                      / "src/starnet/policy/p8_qualification.py").read_text()
        changed = historical.replace(
            'P8_GATE_REPORT_RELATIVE_PATH = "experiments/reports/p8-mean-objective-result-20260913.json"',
            'P8_GATE_REPORT_RELATIVE_PATH = "experiments/reports/p9-result.json"',
        )
        self.assertEqual(qualification_structure(historical), qualification_structure(changed))
        override = historical + '\nqualified_p8_mode = lambda requested: "conservative"\n'
        self.assertNotEqual(qualification_structure(historical), qualification_structure(override))
        duplicate = historical + '\nP8_GATE_REPORT_SHA256 = "' + ("0" * 64) + '"\n'
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            qualification_structure(duplicate)

    def test_archive_member_names_must_be_unique(self):
        self.assertEqual(require_unique_members(["config.json", "starnet_model.py"]),
                         {"config.json", "starnet_model.py"})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            require_unique_members(["config.json", "starnet_model.py", "starnet_model.py"])

    def test_archive_verifier_binds_exact_current_sealed_report(self):
        with tempfile.TemporaryDirectory(prefix="p9-report-bind-") as directory:
            root = Path(directory)
            current = root / "current.json"
            other = root / "other.json"
            payload = {"release_gate_passed": True, "release_gate_pending": None}
            current.write_text(json.dumps(payload))
            other.write_text(json.dumps(payload))
            digest = hashlib.sha256(current.read_bytes()).hexdigest()
            with patch("scripts.verify_p9_release_archive.ROOT", root):
                self.assertEqual(
                    load_current_seal(current, relative_path="current.json", expected_sha256=digest),
                    payload,
                )
                with self.assertRaisesRegex(ValueError, "current qualification"):
                    load_current_seal(other, relative_path="current.json", expected_sha256=digest)

    @staticmethod
    def _seal_inputs():
        protocol = sha(PROTOCOL)
        model_hash = hashlib.sha256(b"model").hexdigest()
        seed = seed_payload("ba_resampled", 901, "saturated_hubs")
        common = {
            "complete": True, "entry_gate_passed": True,
            "model_sha256": model_hash, "bounded_estimator_active": True,
            "unreleased_candidate_assembly": True, "p8_mode": "conservative",
            "transport_errors": 0, "action_failures": 0, "p8_planning_errors": 0,
            "family": "ba_resampled", "repetition": 901, "shift": "saturated_hubs",
            "seed_sha256": seed_sha(seed),
        }
        real = {**common, "llm_mode": "real", "llm_accepted": 1,
                "environment": "public custom-seed sandbox", "public_response_error": 0}
        py39 = {**common, "python_version": "3.9.25", "networkx_version": "3.1",
                "framework_model_module": "casevo.model_base",
                "environment": "corrected local simulator", "llm_mode": "forced_exception_fallback",
                "actions_sha256": "actions", "score": 1.0}
        modern = {**py39, "python_version": "3.12.3", "networkx_version": "3.6.1"}
        snapshot = {relative: sha(Path(__file__).resolve().parents[2] / relative)
                    for relative in expected_runtime_paths()}
        development = {
            "protocol_sha256": protocol, "pairs": 56, "cohort": "development",
            "public_history_resource_audit_passed": True,
            "uncapped_score_equivalence": True, "primary": {"mean": 1.0},
            "source_snapshot": snapshot,
        }
        confirmation = {
            "protocol_sha256": protocol, "pairs": 84, "cohort": "confirmation",
            "statistical_gate_passed": True, "source_snapshot": snapshot,
        }
        return development, confirmation, real, py39, modern

    def test_seal_rejects_wrong_protocol_and_nonmodern_duplicate_entry(self):
        values = self._seal_inputs()
        wrong = dict(values[0], protocol_sha256="0" * 64)
        with patch("scripts.seal_p9_bounded_release.assemble_model", return_value="model"):
            with self.assertRaisesRegex(ValueError, "frozen"):
                seal(wrong, *values[1:])
            with self.assertRaisesRegex(ValueError, "modern"):
                seal(*values[:4], values[3])

    def test_seal_rejects_non_saturated_or_forged_entry_seed(self):
        development, confirmation, real, py39, modern = self._seal_inputs()
        with patch("scripts.seal_p9_bounded_release.assemble_model", return_value="model"):
            with self.assertRaisesRegex(ValueError, "saturated"):
                seal(development, confirmation, dict(real, shift="near_upper_bound"),
                     dict(py39, shift="near_upper_bound"), dict(modern, shift="near_upper_bound"))
            with self.assertRaisesRegex(ValueError, "seed hash"):
                seal(development, confirmation, dict(real, seed_sha256="0" * 64), py39, modern)

    def test_valid_seal_records_protocol_seed_and_legacy_runner_revision(self):
        values = self._seal_inputs()
        legacy = {"commit": "1d6a837", "sha256": "legacy", "legacy_reports_omit_runner_hash": True}
        with patch("scripts.seal_p9_bounded_release.assemble_model", return_value="model"), \
             patch("scripts.seal_p9_bounded_release.historical_entry_runner", return_value=legacy):
            result = seal(*values)
        self.assertTrue(result["release_gate_passed"])
        self.assertEqual(result["entry_runner_evidence"]["historical_execution_tool"], legacy)


if __name__ == "__main__":
    unittest.main()

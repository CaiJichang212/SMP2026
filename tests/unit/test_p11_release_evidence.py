from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_submission
from scripts.build_submission import assemble_model
from scripts.p11_release_common import (
    qualification_structure, require_unique_archive_members, validate_prompt_entry,
)
from scripts.seal_p11_release import PROTOCOL, ROOT, expected_runtime_paths, seal
from starnet.policy import p11_qualification


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(model_hash, *, version="3.12.3", networkx="3.6.1", real=False):
    return {
        "complete": True, "entry_gate_passed": True,
        "model_sha256": model_hash,
        "controller_type": "PromptLearningRuntimeController",
        "p11_experiment_mode": "prompt_learning", "p11_enabled": True,
        "p11_calibration_finished": True, "p11_selected_prompt_id": 2,
        "p11_fallback_to_p9": False, "p11_probe_successes": 3,
        "p11_probe_failures": 0, "p11_probe_budget": 6.0,
        "p11_planning_errors": 0, "p11_errors": 0, "p11_last_error": None,
        "p11_response_switches": 2, "selected_prompt_dispatch_count": 2,
        "action_failures": 0, "p8_planning_errors": 0,
        "one_action_per_host_step": True, "max_actions_per_host_step": 1,
        "unreleased_candidate_assembly": True,
        "python_version": version, "networkx_version": networkx,
        "framework_model_module": "casevo.model_base",
        "seed_sha256": "b" * 64,
        "llm_mode": "real" if real else "mock",
        "llm_accepted": 1, "environment": "public custom-seed sandbox" if real else "local",
        "result": {
            "score": 123.0, "action_sha256": "a" * 64,
            "public_response_error": 0 if real else None,
            "transport_errors": 0,
        },
    }


class P11ReleaseEvidenceTests(unittest.TestCase):
    def test_nested_entry_requires_nonempty_action_hash_and_finite_score(self):
        model_hash = "c" * 64
        valid = entry(model_hash)
        normalized = validate_prompt_entry(valid, model_hash)
        self.assertEqual(normalized["action_sha256"], "a" * 64)
        missing = entry(model_hash)
        missing["result"]["action_sha256"] = None
        with self.assertRaisesRegex(ValueError, "identity or score"):
            validate_prompt_entry(missing, model_hash)
        conflict = entry(model_hash)
        conflict["action_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "conflicting"):
            validate_prompt_entry(conflict, model_hash)

    def test_qualification_normalization_allows_only_three_literal_values(self):
        source = (ROOT / "src/starnet/policy/p11_qualification.py").read_text()
        # Exercise the same fixture before and after a real release activates
        # metadata; a successful release must not turn replacements into no-ops.
        for name in ("P11_CERTIFIED_MODE", "P11_GATE_REPORT_SHA256",
                     "P11_GATE_REPORT_RELATIVE_PATH"):
            source, count = re.subn(
                rf"^{name}: str \| None = .+$",
                f"{name}: str | None = None", source, flags=re.MULTILINE,
            )
            self.assertEqual(count, 1)
        changed = source.replace(
            "P11_CERTIFIED_MODE: str | None = None",
            'P11_CERTIFIED_MODE: str | None = "prompt_learning"',
        )
        self.assertEqual(qualification_structure(source), qualification_structure(changed))
        override = source + '\nqualified_p11_mode = lambda value: "prompt_learning"\n'
        self.assertNotEqual(qualification_structure(source), qualification_structure(override))
        executable = source.replace(
            "P11_GATE_REPORT_SHA256: str | None = None",
            'P11_GATE_REPORT_SHA256: str | None = "a" * 64',
        )
        with self.assertRaisesRegex(ValueError, "literal"):
            qualification_structure(executable)

    def test_archive_member_names_reject_duplicates(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            require_unique_archive_members(["config.json", "starnet_model.py", "starnet_model.py"])

    def test_activation_seal_requires_both_gates_and_stays_pre_zip(self):
        protocol_hash = digest(PROTOCOL)
        snapshot = {relative: digest(ROOT / relative) for relative in expected_runtime_paths()}
        development = {
            "protocol_sha256": protocol_hash, "cases": 252,
            "development_gate_passed": True, "selected_variant": "prompt_learning",
            "source_snapshot": snapshot,
        }
        confirmation = {
            "protocol_sha256": protocol_hash, "cases": 360,
            "statistical_gate_passed": True, "selected_variant": "prompt_learning",
            "source_snapshot": snapshot,
        }
        model_hash = hashlib.sha256(assemble_model().encode()).hexdigest()
        real = entry(model_hash, real=True)
        py39 = entry(model_hash, version="3.9.25", networkx="3.1")
        modern = entry(model_hash)
        qualification = (ROOT / "src/starnet/policy/p11_qualification.py").read_bytes()
        with patch("scripts.seal_p11_release.subprocess.check_output",
                   return_value=qualification) as historical:
            result = seal(
                development, confirmation, real, py39, modern,
                validated_commit="unit-test-fixture",
            )
        historical.assert_called_once_with(
            ["git", "show", "unit-test-fixture:src/starnet/policy/p11_qualification.py"],
            cwd=ROOT,
        )
        self.assertTrue(result["activation_seal_passed"])
        self.assertTrue(result["unreleased_entry_gate_passed"])
        self.assertFalse(result["release_gate_passed"])
        self.assertIn("final ZIP execution", result["release_gate_pending"])
        with patch("scripts.seal_p11_release.subprocess.check_output",
                   return_value=b"mismatched qualification source"):
            with self.assertRaisesRegex(ValueError, "validated commit"):
                seal(development, confirmation, real, py39, modern,
                     validated_commit="unit-test-fixture")
        rejected = dict(confirmation, statistical_gate_passed=False)
        with self.assertRaisesRegex(ValueError, "confirmation"):
            seal(development, rejected, real, py39, modern,
                 validated_commit="07ac5f9")

    def test_build_rejects_statistical_pass_without_p11_activation_seal(self):
        with tempfile.TemporaryDirectory(prefix="p11-build-gate-") as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "config.json").write_text(json.dumps({"person": [{
                "role": "CommanderAgent", "experimental_p11_mode": "prompt_learning",
            }]}))
            report = root / "experiments/reports/p11.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({
                "selected_variant": "prompt_learning",
                "statistical_gate_passed": True,
                "activation_seal_passed": False,
            }))
            report_hash = hashlib.sha256(report.read_bytes()).hexdigest()
            with patch.object(build_submission, "PROJECT_ROOT", root), \
                 patch.object(build_submission, "SOURCE_DIR", source), \
                 patch.object(p11_qualification, "P11_CERTIFIED_MODE", "prompt_learning"), \
                 patch.object(p11_qualification, "P11_GATE_REPORT_RELATIVE_PATH",
                              "experiments/reports/p11.json"), \
                 patch.object(p11_qualification, "P11_GATE_REPORT_SHA256", report_hash):
                with self.assertRaisesRegex(SystemExit, "entry activation seal"):
                    build_submission.verify_p11_release()


if __name__ == "__main__":
    unittest.main()

"""Contract tests for the non-enabling P10 integration preview."""

from types import SimpleNamespace
import unittest

from scripts.preview_p10_release_integration import (
    resolve_preview_mode,
    runner_rebuild_options,
)


class P10ReleaseIntegrationPreviewTests(unittest.TestCase):
    def test_missing_flag_defaults_to_certified_combined(self):
        self.assertEqual(resolve_preview_mode(
            {}, certified_mode="combined", report_sha256="a" * 64,
        ), "combined")
        self.assertEqual(resolve_preview_mode(
            {"experimental_p10_mode": "combined"},
            certified_mode="combined", report_sha256="a" * 64,
        ), "combined")

    def test_explicit_unknown_or_missing_certificate_falls_back(self):
        for description in (
            {"experimental_p10_mode": "plan_only"},
            {"experimental_p10_mode": "future"},
            {"experimental_p10_mode": None},
        ):
            self.assertIsNone(resolve_preview_mode(
                description, certified_mode="combined", report_sha256="a" * 64,
            ))
        self.assertIsNone(resolve_preview_mode(
            {}, certified_mode=None, report_sha256=None,
        ))

    def test_runner_rebuild_preserves_bounds_but_resets_estimator(self):
        original = SimpleNamespace(
            p8_mode="conservative", p10_experiment_mode="combined",
            p10_max_structures=12, p10_beam_width=4,
            p10_response_estimator=object(),
        )
        self.assertEqual(runner_rebuild_options(original), {
            "p8_mode": "conservative",
            "require_stage_envelope": True,
            "experiment_mode": "combined",
            "max_structures": 12,
            "beam_width": 4,
            "response_estimator": None,
        })

    def test_runner_keeps_p9_when_p10_is_absent(self):
        original = SimpleNamespace(p8_mode="conservative")
        self.assertEqual(runner_rebuild_options(original), {
            "p8_mode": "conservative", "require_stage_envelope": True,
        })


if __name__ == "__main__":
    unittest.main()

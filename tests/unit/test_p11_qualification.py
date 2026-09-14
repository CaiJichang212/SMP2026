from __future__ import annotations

import unittest
from unittest.mock import patch

from starnet.policy import p11_qualification


class P11QualificationTests(unittest.TestCase):
    def test_default_metadata_is_fail_closed(self):
        self.assertIsNone(p11_qualification.P11_CERTIFIED_MODE)
        self.assertIsNone(p11_qualification.P11_GATE_REPORT_SHA256)
        self.assertIsNone(p11_qualification.P11_GATE_REPORT_RELATIVE_PATH)
        self.assertIsNone(p11_qualification.qualified_p11_mode("prompt_learning"))

    def test_only_exact_sealed_mode_and_report_identity_can_enable(self):
        with patch.object(p11_qualification, "P11_CERTIFIED_MODE", "prompt_learning"), \
             patch.object(p11_qualification, "P11_GATE_REPORT_SHA256", "a" * 64), \
             patch.object(p11_qualification, "P11_GATE_REPORT_RELATIVE_PATH",
                          "experiments/reports/p11-release.json"):
            self.assertEqual(
                p11_qualification.qualified_p11_mode("prompt_learning"),
                "prompt_learning",
            )
            for requested in (None, "combined", "PROMPT_LEARNING", 1):
                self.assertIsNone(p11_qualification.qualified_p11_mode(requested))

    def test_missing_or_out_of_scope_report_metadata_stays_closed(self):
        for digest, path in (("short", "experiments/reports/p11.json"),
                             ("b" * 64, "artifacts/p11.json"),
                             ("b" * 64, None)):
            with patch.object(p11_qualification, "P11_CERTIFIED_MODE", "prompt_learning"), \
                 patch.object(p11_qualification, "P11_GATE_REPORT_SHA256", digest), \
                 patch.object(p11_qualification, "P11_GATE_REPORT_RELATIVE_PATH", path):
                self.assertIsNone(p11_qualification.qualified_p11_mode("prompt_learning"))


if __name__ == "__main__":
    unittest.main()

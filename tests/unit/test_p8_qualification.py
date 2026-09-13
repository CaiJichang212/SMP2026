import unittest
from unittest.mock import patch

import starnet.policy.p8_qualification as qualification


class P8QualificationTests(unittest.TestCase):
    def test_missing_qualification_never_enables_requested_policy(self):
        with patch.object(qualification, "P8_CERTIFIED_MODE", None):
            for request in (None, "conservative", "audited", True, {}):
                self.assertIsNone(qualification.qualified_p8_mode(request))

    def test_only_exact_reviewed_variant_with_report_can_enable(self):
        with patch.object(qualification, "P8_CERTIFIED_MODE", "audited"), \
             patch.object(qualification, "P8_GATE_REPORT_SHA256", "a" * 64):
            self.assertEqual(qualification.qualified_p8_mode("audited"), "audited")
            self.assertIsNone(qualification.qualified_p8_mode("conservative"))
            self.assertIsNone(qualification.qualified_p8_mode(None))
        with patch.object(qualification, "P8_CERTIFIED_MODE", "audited"), \
             patch.object(qualification, "P8_GATE_REPORT_SHA256", None):
            self.assertIsNone(qualification.qualified_p8_mode("audited"))


if __name__ == "__main__":
    unittest.main()

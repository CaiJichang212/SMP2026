"""Fail-closed checks for the P11 full anchor screen."""

import unittest

from scripts.run_p11_anchor_full import validate_control_audit


class P11AnchorFullRunnerTests(unittest.TestCase):
    def test_control_audit_must_bind_complete_original_raw(self):
        class Path:
            def __init__(self, digest):
                self.digest = digest

            def read_bytes(self):
                return self.digest

        control = Path(b"control")
        import hashlib
        value = {"cohort": "development", "cases": 252,
                 "input_sha256": hashlib.sha256(b"control").hexdigest(),
                 "source_snapshot": {"runtime": "hash"},
                 "identification_passed": True, "resource_audit_passed": True,
                 "calibration_audit_passed": True}
        validate_control_audit(value, control, {"source_snapshot": {"runtime": "hash"}})
        for field in ("identification_passed", "resource_audit_passed",
                      "calibration_audit_passed"):
            broken = dict(value)
            broken[field] = False
            with self.assertRaises(ValueError):
                validate_control_audit(broken, control,
                                       {"source_snapshot": {"runtime": "hash"}})


if __name__ == "__main__":
    unittest.main()

"""Static guarantees for the final P11 ZIP checker."""

from pathlib import Path
import unittest

from scripts.check_p11_release_entry import base_report


class P11ReleaseEntryTests(unittest.TestCase):
    def test_report_identity_is_final_and_not_unreleased(self):
        class File:
            def __init__(self, name, value):
                self.name, self.value = name, value

            def read_bytes(self):
                return self.value

            def __str__(self):
                return self.name

        class Args:
            family = "er_balanced"
            prompt_case = "prompt2_best"
            llm_mode = "mock"
            remote = False
        report = base_report(File("final.zip", b"zip"), File("model.py", b"model"),
                             {"seed": 1}, Args())
        self.assertTrue(report["final_zip_execution"])
        self.assertFalse(report["unreleased_candidate_assembly"])
        self.assertFalse(report["qualification_injected_after_import"])
        self.assertFalse(report["controller_replaced_after_construction"])

    def test_checker_has_no_qualification_metadata_injection(self):
        source = (Path(__file__).resolve().parents[2]
                  / "scripts/check_p11_release_entry.py").read_text(encoding="utf-8")
        self.assertNotIn("setattr(module", source)
        self.assertNotIn('P11_GATE_REPORT_SHA256 =', source)
        self.assertNotIn('P11_CERTIFIED_MODE =', source)


if __name__ == "__main__":
    unittest.main()

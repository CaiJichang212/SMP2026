"""Historical archive loading and common environment rules."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from scripts.compare_submission_archives import CountingLLM, CurrentRulesEnvironment, extract_submission
from starnet.experiments.seeds import seed_payload


class ArchiveComparisonTests(unittest.TestCase):
    def test_offline_llm_blocks_before_any_remote_attempt(self):
        llm = CountingLLM(20, offline_only=True)
        with self.assertRaisesRegex(RuntimeError, "network disabled"):
            llm.send_message("public synthetic test")
        self.assertEqual(llm.attempts, 0)
        self.assertEqual(llm.blocked_calls, 1)

    def test_archive_paths_cannot_escape_isolation_directory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "unsafe.zip"
            with ZipFile(archive, "w") as bundle:
                bundle.writestr("../outside.py", "pass")
            with self.assertRaises(ValueError):
                extract_submission(archive, root / "extracted")
            self.assertFalse((root / "outside.py").exists())

    def test_failed_structure_is_charged_but_failed_scan_and_comm_are_not(self):
        env = CurrentRulesEnvironment(seed_payload("er_balanced"))
        self.assertIsNone(env.scan_node(999))
        env.communicate(999, 1)
        self.assertEqual(env.get_remaining_budget(), 100)
        self.assertFalse(env.cut_link(998, 999))
        self.assertEqual(env.get_remaining_budget(), 97)
        self.assertFalse(env.shield_node(999))
        self.assertEqual(env.get_remaining_budget(), 92)

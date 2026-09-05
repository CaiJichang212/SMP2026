"""OpenAI Chat Completions 兼容适配器的协议测试。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.openai_compat import OpenAICompatibleChat, chat_completions_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class OpenAICompatibleChatTests(unittest.TestCase):
    def test_url_normalization_preserves_or_adds_v1_once(self) -> None:
        self.assertEqual(
            chat_completions_url("http://43.133.177.230:3819/v1/"),
            "http://43.133.177.230:3819/v1/chat/completions",
        )
        self.assertEqual(
            chat_completions_url("https://gateway.example"),
            "https://gateway.example/v1/chat/completions",
        )

    @patch("scripts.openai_compat.requests.post")
    def test_requests_standard_json_chat_completion(self, post: object) -> None:
        post.return_value = SimpleNamespace(
            ok=True,
            json=lambda: {"choices": [{"message": {"content": '{"candidate_ids":["cut:2-3"]}'}}]},
        )
        client = OpenAICompatibleChat("secret", "http://gateway/v1", "gpt-5.6-luna", 12.0)

        self.assertEqual(client.complete_json("rank these"), '{"candidate_ids":["cut:2-3"]}')
        self.assertEqual(post.call_args.args[0], "http://gateway/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(post.call_args.kwargs["json"], {
            "model": "gpt-5.6-luna",
            "messages": [{"role": "user", "content": "rank these"}],
            "response_format": {"type": "json_object"},
        })

    @patch("scripts.openai_compat.requests.post")
    def test_http_failure_is_reported_without_retry(self, post: object) -> None:
        post.return_value = SimpleNamespace(ok=False, status_code=400)
        client = OpenAICompatibleChat("secret", "http://gateway/v1", "gpt-5.6-luna", 12.0)

        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            client.complete_json("rank these")
        post.assert_called_once()

    def test_public_scripts_start_when_executed_by_path(self) -> None:
        """The documented commands execute files, not ``scripts.*`` modules."""
        for script in ("run_baseline_openai.py", "run_experiments.py"):
            result = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / script), "--help"],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=f"{script}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()

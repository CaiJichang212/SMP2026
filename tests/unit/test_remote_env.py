"""远程沙盒适配器的协议校验测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import requests


STARTER_KIT = Path(__file__).resolve().parents[2] / "SMP_Starter_Kit"
sys.path.insert(0, str(STARTER_KIT))

from api_client import RemoteProtocolError, RemoteStarNetEnv


class RemoteEnvTests(TestCase):
    def response(self, body: object, *, status_error: Exception | None = None) -> Mock:
        response = Mock()
        response.json.return_value = body
        response.raise_for_status.side_effect = status_error
        return response

    def start_env(self, post: Mock) -> RemoteStarNetEnv:
        post.return_value = self.response({"session_id": "test-session"})
        return RemoteStarNetEnv("https://sandbox.invalid", {"nodes": []}, timeout=1.0)

    @patch("api_client.requests.post")
    def test_budget_requires_numeric_value(self, post: Mock) -> None:
        env = self.start_env(post)
        post.return_value = self.response({"budget": "20"})

        with self.assertRaises(RemoteProtocolError):
            env.get_remaining_budget()
        self.assertIn("/api/get_budget", env.last_protocol_error or "")

    @patch("api_client.requests.post")
    def test_scan_validates_nested_data_shape(self, post: Mock) -> None:
        env = self.start_env(post)
        post.return_value = self.response({"data": {"w": 1, "persona": "和平"}})

        with self.assertRaises(RemoteProtocolError):
            env.scan_node(1)

    @patch("api_client.requests.post")
    def test_scan_allows_documented_null_for_missing_node(self, post: Mock) -> None:
        env = self.start_env(post)
        post.return_value = self.response({"data": None})

        self.assertIsNone(env.scan_node(99))

    @patch("api_client.requests.post")
    def test_scan_allows_unreported_communication_quota(self, post: Mock) -> None:
        env = self.start_env(post)
        data = {"w": 1, "persona": "和平", "neighbors": [2]}
        post.return_value = self.response({"data": data})

        self.assertEqual(env.scan_node(1), data)

    @patch("api_client.requests.post")
    def test_http_error_is_not_converted_to_zero_or_false(self, post: Mock) -> None:
        env = self.start_env(post)
        post.return_value = self.response({}, status_error=requests.HTTPError("HTTP 500"))

        with self.assertRaises(RemoteProtocolError):
            env.get_remaining_budget()

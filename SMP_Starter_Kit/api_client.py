"""赛方远程沙盒的公开 HTTP API 适配器。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import requests


DEFAULT_TIMEOUT_SECONDS = 30.0
SCAN_FIELDS = frozenset({"w", "persona", "neighbors"})


class RemoteProtocolError(RuntimeError):
    """远程沙盒没有遵守已知公开协议时抛出，不包含响应正文。"""

    def __init__(self, endpoint: str, detail: str) -> None:
        super().__init__(f"remote sandbox protocol error at {endpoint}: {detail}")


class RemoteStarNetEnv:
    def __init__(
        self,
        api_url: str,
        custom_seed_data: Mapping[str, Any] | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.last_protocol_error: str | None = None
        session = self._post("/api/start_session", {"seed": custom_seed_data})
        session_id = session.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise self._error("/api/start_session", "missing string field session_id")
        self.session_id = session_id

    def _error(self, endpoint: str, detail: str) -> RemoteProtocolError:
        error = RemoteProtocolError(endpoint, detail)
        self.last_protocol_error = str(error)
        return error

    def _post(self, endpoint: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            response = requests.post(f"{self.api_url}{endpoint}", json=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise self._error(endpoint, f"request failed ({type(exc).__name__})") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise self._error(endpoint, "response is not JSON") from exc
        if not isinstance(body, dict):
            raise self._error(endpoint, "response JSON must be an object")
        return body

    def get_remaining_budget(self) -> float:
        body = self._post("/api/get_budget", {"session_id": self.session_id})
        budget = body.get("budget")
        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            raise self._error("/api/get_budget", "missing numeric field budget")
        return float(budget)

    def scan_node(self, node_id: int) -> dict[str, Any] | None:
        body = self._post("/api/scan", {"session_id": self.session_id, "node_id": node_id})
        if "data" not in body:
            raise self._error("/api/scan", "missing field data")
        data = body["data"]
        if data is None:
            return None
        if not isinstance(data, dict):
            raise self._error("/api/scan", "field data must be an object or null")
        missing = SCAN_FIELDS.difference(data)
        if missing:
            raise self._error(
                "/api/scan",
                f"data missing fields {sorted(missing)}; available fields {sorted(data)}",
            )
        if not isinstance(data["neighbors"], list):
            raise self._error("/api/scan", "data.neighbors must be a list")
        return data

    def communicate(self, node_id: int, prompt_id: int) -> dict[str, Any]:
        body = self._post(
            "/api/communicate",
            {"session_id": self.session_id, "node_id": node_id, "prompt_id": prompt_id},
        )
        if not isinstance(body.get("status"), str):
            raise self._error("/api/communicate", "missing string field status")
        return body

    def cut_link(self, u: int, v: int) -> bool:
        body = self._post("/api/cut", {"session_id": self.session_id, "u": u, "v": v})
        success = body.get("success")
        if not isinstance(success, bool):
            raise self._error("/api/cut", "missing boolean field success")
        return success

    def shield_node(self, node_id: int) -> bool:
        body = self._post("/api/shield", {"session_id": self.session_id, "node_id": node_id})
        success = body.get("success")
        if not isinstance(success, bool):
            raise self._error("/api/shield", "missing boolean field success")
        return success

    def trigger_eval(self) -> float:
        """让服务器进行物理共识推演结算。"""
        body = self._post("/api/evaluate", {"session_id": self.session_id})
        final_score = body.get("final_score")
        if isinstance(final_score, bool) or not isinstance(final_score, (int, float)):
            raise self._error("/api/evaluate", "missing numeric field final_score")
        return float(final_score)

"""Small, dependency-free client for OpenAI Chat Completions compatible APIs.

The contest runtime only needs a single non-streaming JSON response.  Keeping
this adapter on ``requests`` avoids coupling the submission or CaseVO to any
one model provider while retaining the standard OpenAI-compatible wire format.
"""

from __future__ import annotations

from typing import Any, Mapping

import requests


DEFAULT_BASE_URL = "http://43.133.177.230:3819/v1"
DEFAULT_MODEL = "gpt-5.6-luna"


def chat_completions_url(base_url: str) -> str:
    """Normalize a provider base URL to its Chat Completions endpoint.

    OpenAI-compatible providers conventionally expose ``/v1``.  Accepting a
    URL with or without that suffix prevents the common accidental ``/v1/v1``
    endpoint while keeping the final request OpenAI API shaped.
    """
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("SMP_LLM_BASE_URL must not be empty")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return f"{normalized}/chat/completions"


class OpenAICompatibleChat:
    """Call a Chat Completions compatible model and return message content."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float) -> None:
        if not api_key.strip():
            raise ValueError("SMP_LLM_API_KEY must not be empty")
        if not model.strip():
            raise ValueError("SMP_LLM_MODEL must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key
        self.url = chat_completions_url(base_url)
        self.model = model
        self.timeout = timeout

    def complete_json(self, prompt: str) -> str:
        """Request one JSON-object completion without implicit retries.

        An adapter retry would be another remote LLM request but invisible to
        the controller's quota, so all provider failures surface immediately
        and the controller selects its deterministic fallback.
        """
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        response = requests.post(
            self.url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        if not response.ok:
            raise RuntimeError(f"OpenAI-compatible request failed with HTTP {response.status_code}")
        try:
            payload: Mapping[str, Any] = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("OpenAI-compatible response had no chat completion") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenAI-compatible response contained an empty chat completion")
        return content

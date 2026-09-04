"""Best-effort structured diagnostics for local StarNet runs.

The trace is deliberately a side channel: a failed sink is disabled and never
allowed to affect controller decisions or environment calls.  Submission code
does not create a trace; local tools inject one before the first ``step``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Protocol


TRACE_SCHEMA_VERSION = 1
_REDACTED = "[REDACTED]"
_TRUNCATED = "...[truncated]"
_MAX_STRING_LENGTH = 2_000
_MAX_ERROR_LENGTH = 500
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "headers",
    "password",
    "secret",
    "token",
)
_BEARER_VALUE = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|token)\s*[=:]\s*[^\s,;]+"
)


class TraceSink(Protocol):
    """One destination for already structured trace records."""

    def emit(self, record: Mapping[str, Any]) -> None: ...


def _safe_string(value: str, limit: int = _MAX_STRING_LENGTH) -> str:
    value = _BEARER_VALUE.sub(r"\1" + _REDACTED, value)
    value = _SECRET_ASSIGNMENT.sub(r"\1=" + _REDACTED, value)
    return value if len(value) <= limit else value[:limit] + _TRUNCATED


def safe_json_value(value: Any, *, _key: str | None = None) -> Any:
    """Return a JSON-safe, bounded and credential-redacted representation."""
    normalized_key = "" if _key is None else _key.lower().replace("-", "_")
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return _REDACTED
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _safe_string(value)
    if isinstance(value, bytes):
        return _safe_string(value.decode("utf-8", errors="replace"))
    if isinstance(value, Enum):
        return safe_json_value(value.value, _key=_key)
    if is_dataclass(value) and not isinstance(value, type):
        return safe_json_value(asdict(value), _key=_key)
    if isinstance(value, Mapping):
        return {
            _safe_string(str(key), 200): safe_json_value(item, _key=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (set, frozenset)):
        return [safe_json_value(item) for item in sorted(value, key=repr)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [safe_json_value(item) for item in value]
    return _safe_string(f"<{type(value).__name__}>", 200)


def safe_error(exc: BaseException) -> dict[str, str]:
    """Keep useful exception context without serializing exception internals."""
    return {
        "type": type(exc).__name__,
        "message": _safe_string(str(exc), _MAX_ERROR_LENGTH),
    }


class JsonlTraceSink:
    """Append one flushed JSON document per event to a local file."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("a", encoding="utf-8")

    def emit(self, record: Mapping[str, Any]) -> None:
        self._file.write(json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False))
        self._file.write("\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class ConsoleTraceSink:
    """Compact local progress display, intentionally limited to outer steps."""

    def __init__(self, stream: Any | None = None) -> None:
        self.stream = sys.stdout if stream is None else stream

    def emit(self, record: Mapping[str, Any]) -> None:
        if record.get("event") != "step.completed":
            return
        data = record.get("data")
        if not isinstance(data, Mapping):
            return
        action = data.get("action")
        if isinstance(action, Mapping):
            action_text = str(action.get("kind", "action"))
            target = action.get("target_node_1")
            if target is not None:
                action_text += f":{target}"
            second = action.get("target_node_2")
            if second is not None:
                action_text += f"-{second}"
        else:
            action_text = "none"
        result = data.get("action_result", "idle")
        old_state = data.get("state_before", record.get("state"))
        new_state = record.get("state")
        selected = data.get("selected_candidate_ids")
        selected_text = ""
        if isinstance(selected, list) and selected:
            selected_text = f" selected={','.join(str(item) for item in selected)}"
        print(
            f"step={record.get('step')} {old_state}->{new_state} "
            f"action={action_text} budget={record.get('budget_before')}->{record.get('budget_after')} "
            f"result={result}{selected_text}",
            file=self.stream,
            flush=True,
        )


class RuntimeTrace:
    """Fan out ordered trace events while quarantining faulty destinations."""

    def __init__(
        self,
        *,
        run_id: str,
        seed_id: str,
        sinks: Sequence[TraceSink] = (),
    ) -> None:
        self.run_id = str(run_id)
        self.seed_id = str(seed_id)
        self._sinks: list[TraceSink] = list(sinks)
        self._sequence = 0

    @property
    def enabled(self) -> bool:
        return bool(self._sinks)

    @property
    def sequence(self) -> int:
        return self._sequence

    def emit(
        self,
        event: str,
        *,
        step: int,
        state: object,
        budget_before: float | None,
        budget_after: float | None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        if not self._sinks:
            return
        self._sequence += 1
        try:
            record = {
                "schema_version": TRACE_SCHEMA_VERSION,
                "run_id": self.run_id,
                "seed_id": self.seed_id,
                "seq": self._sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
                "event": str(event),
                "step": int(step),
                "state": safe_json_value(state),
                "budget_before": safe_json_value(budget_before),
                "budget_after": safe_json_value(budget_after),
                "data": safe_json_value(data or {}),
            }
        except Exception:
            # If a caller supplies an unserializable diagnostic object, all
            # destinations are disabled instead of leaking into strategy flow.
            self.close()
            return
        healthy: list[TraceSink] = []
        for sink in self._sinks:
            try:
                sink.emit(record)
            except Exception:
                # A trace sink is diagnostic only.  Do not recursively report its failure.
                close = getattr(sink, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            else:
                healthy.append(sink)
        self._sinks = healthy

    def close(self) -> None:
        for sink in self._sinks:
            close = getattr(sink, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._sinks = []


class NullRuntimeTrace(RuntimeTrace):
    """Allocation-free controller default used by the submission entry point."""

    def __init__(self) -> None:
        super().__init__(run_id="", seed_id="", sinks=())


__all__ = [
    "ConsoleTraceSink",
    "JsonlTraceSink",
    "NullRuntimeTrace",
    "RuntimeTrace",
    "TRACE_SCHEMA_VERSION",
    "TraceSink",
    "safe_error",
    "safe_json_value",
]

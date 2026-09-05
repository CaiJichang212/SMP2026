#!/usr/bin/env python3
"""Fail closed when the local SDK contract differs from the P0 lock."""

from __future__ import annotations

import importlib.metadata
import inspect
import sys

from casevo import AgentBase, ModelBase


EXPECTED_PYTHON = (3, 12, 3)
EXPECTED_VERSIONS = {
    "casevo": "0.3.19",
    "mesa": "2.4.0",
    "networkx": "3.6.1",
    "chromadb": "1.5.9",
}
EXPECTED_MODEL_SIGNATURE = "(self, tar_graph, llm, context=None, prompt_path='./prompt/', memory_path=None, memory_num=10, reflect_file='reflect.txt', type_schedule=False)"
EXPECTED_AGENT_SIGNATURE = "(self, unique_id, model, description, context)"


def main() -> int:
    errors: list[str] = []
    if sys.version_info[:3] != EXPECTED_PYTHON:
        errors.append(f"python={sys.version_info[:3]} expected={EXPECTED_PYTHON}")
    for package, expected in EXPECTED_VERSIONS.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = "missing"
        if actual != expected:
            errors.append(f"{package}={actual} expected={expected}")
    for label, actual, expected in (
        ("ModelBase.__init__", str(inspect.signature(ModelBase.__init__)), EXPECTED_MODEL_SIGNATURE),
        ("AgentBase.__init__", str(inspect.signature(AgentBase.__init__)), EXPECTED_AGENT_SIGNATURE),
    ):
        if actual != expected:
            errors.append(f"{label}={actual!r} expected={expected!r}")
    if errors:
        print("[failed] P0 runtime contract mismatch")
        print("\n".join(errors))
        return 1
    print("[passed] P0 runtime contract is locked and compatible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

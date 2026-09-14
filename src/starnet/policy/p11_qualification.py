"""Fail-closed qualification metadata for public prompt learning.

Canonical integration may import this module before confirmation. The default
values deliberately keep P11 disabled; a release seal may later update only
the three metadata constants after all statistical and entry gates pass.
"""

from __future__ import annotations


P11_CERTIFIED_MODE: str | None = "prompt_learning"
P11_GATE_REPORT_SHA256: str | None = "438b8fe498e4ea2f649bf3e297cdc39972865cbf2233788a23c36bf325b9ceae"
P11_GATE_REPORT_RELATIVE_PATH: str | None = "experiments/reports/p11-prompt-learning-activation-20260914.json"


def qualified_p11_mode(requested: object) -> str | None:
    if (
        P11_CERTIFIED_MODE == "prompt_learning"
        and requested == P11_CERTIFIED_MODE
        and isinstance(P11_GATE_REPORT_SHA256, str)
        and len(P11_GATE_REPORT_SHA256) == 64
        and isinstance(P11_GATE_REPORT_RELATIVE_PATH, str)
        and P11_GATE_REPORT_RELATIVE_PATH.startswith("experiments/reports/")
    ):
        return P11_CERTIFIED_MODE
    return None


__all__ = [
    "P11_CERTIFIED_MODE", "P11_GATE_REPORT_RELATIVE_PATH",
    "P11_GATE_REPORT_SHA256", "qualified_p11_mode",
]

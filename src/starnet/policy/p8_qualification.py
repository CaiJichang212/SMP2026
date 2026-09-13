"""Qualification for the public-response-bound correction to conservative P8.

The separate 84-pair confirmation and entry evidence are sealed in the
referenced report. Historical P8 qualification reports remain unchanged.
"""

from __future__ import annotations

P8_CERTIFIED_MODE: str | None = "conservative"
P8_GATE_REPORT_SHA256: str | None = "a2a988f6288cb1217c5b69c8b2e4f893b060bd5cb7e1e10a2088d074a405f25a"
P8_GATE_REPORT_RELATIVE_PATH = "experiments/reports/p9-bounded-release-result-20260913.json"


def qualified_p8_mode(requested: object) -> str | None:
    if (P8_CERTIFIED_MODE in ("conservative", "audited")
            and requested == P8_CERTIFIED_MODE
            and isinstance(P8_GATE_REPORT_SHA256, str)
            and len(P8_GATE_REPORT_SHA256) == 64):
        return P8_CERTIFIED_MODE
    return None

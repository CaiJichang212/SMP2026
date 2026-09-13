"""Local mean-objective qualification, not per-family noninferiority.

New repetitions 701--705 passed the preregistered mean/composition criterion;
the earlier 601--605 strict gate remains failed. Unqualified requests close.
"""

P8_CERTIFIED_MODE: str | None = "conservative"
P8_GATE_REPORT_SHA256: str | None = "0594442f917eacbffe553bb7499b832d31a8b8fde12ba47c6479573ec464850c"
P8_POLICY_SHA256 = "56709076b9c89d7934899f046c20198f569575b165871adfc9055e49269500b0"


def qualified_p8_mode(requested: object) -> str | None:
    if (P8_CERTIFIED_MODE in ("conservative", "audited")
            and requested == P8_CERTIFIED_MODE
            and isinstance(P8_GATE_REPORT_SHA256, str)
            and len(P8_GATE_REPORT_SHA256) == 64):
        return P8_CERTIFIED_MODE
    return None

"""Reviewed qualification only; unqualified submission requests fail closed."""

P8_CERTIFIED_MODE: str | None = None
P8_GATE_REPORT_SHA256: str | None = None


def qualified_p8_mode(requested: object) -> str | None:
    if (P8_CERTIFIED_MODE in ("conservative", "audited")
            and requested == P8_CERTIFIED_MODE
            and isinstance(P8_GATE_REPORT_SHA256, str)
            and len(P8_GATE_REPORT_SHA256) == 64):
        return P8_CERTIFIED_MODE
    return None

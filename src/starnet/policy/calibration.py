"""Frozen, serialisable V1 calibration data.

This module intentionally contains no file I/O.  Offline tools build a
profile, verify its hashes, then copy its literal payload here before a CMG
submission can be enabled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Mapping


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class CalibrationProfile:
    """All runtime CMG assumptions, with provenance and a fail-closed gate."""

    gate_passed: bool
    model: str = "degree"
    rho: float = 0.0
    gamma: float = 0.0
    a: float = 0.5
    b: float = 0.0
    settlement_residual_std: Mapping[str, float] = field(default_factory=dict)
    response_mean: Mapping[str, float] = field(default_factory=dict)
    response_std: Mapping[str, float] = field(default_factory=dict)
    manifest_hash: str = ""
    data_hash: str = ""
    profile_hash: str = ""
    # Values are public, held-out-validated terminal influence coefficients.
    # An empty map is intentional: it makes B2 unavailable rather than guessed.
    target_influence: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.model not in {"degree", "degroot", "friedkin_johnsen"}:
            raise ValueError("unknown settlement model")
        for value in (self.rho, self.gamma, self.a, self.b):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("calibration parameters must be finite")
        for values in (self.settlement_residual_std, self.response_mean, self.response_std, self.target_influence):
            for value in values.values():
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("calibration values must be finite")
        expected = self.computed_hash()
        if self.profile_hash and self.profile_hash != expected:
            raise ValueError("CalibrationProfile profile_hash does not match payload")

    @staticmethod
    def response_key(persona: str, prompt_id: int, turn: int) -> str:
        return f"{persona}|{prompt_id}|{turn}"

    def computed_hash(self) -> str:
        payload = asdict(self)
        payload["profile_hash"] = ""
        return canonical_hash(payload)

    @property
    def verified(self) -> bool:
        return bool(self.gate_passed and self.manifest_hash and self.data_hash and self.profile_hash == self.computed_hash())

    def response_prior(self, persona: str, prompt_id: int, turn: int) -> tuple[float, float] | None:
        key = self.response_key(persona, prompt_id, turn)
        mean = self.response_mean.get(key)
        std = self.response_std.get(key)
        if mean is None or std is None:
            return None
        return float(mean), max(0.0, float(std))

    def residual_for(self, action_kind: str) -> float:
        value = self.settlement_residual_std.get(action_kind)
        return max(0.0, float(value)) if value is not None else math.inf

    @property
    def b2_eligible(self) -> bool:
        return self.verified and bool(self.target_influence)


# Deliberately fail closed until ``scripts/calibrate_v1.py freeze`` emits a
# reviewed literal profile.  Runtime code never reads experiment artefacts.
DEFAULT_CALIBRATION_PROFILE = CalibrationProfile(gate_passed=False)

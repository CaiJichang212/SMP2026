"""Immutable, auditable switches for V0 policy experiments.

The submission always uses :data:`DEFAULT_POLICY_CONFIG`.  Experiment tools may
pass another instance to ``RuntimeController`` without changing the official
``ParticipantSquadModel(host_env, person_list, llm)`` contract.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyConfig:
    """All V0 tuning knobs, deliberately small and serialisable.

    ``max_llm_calls`` is the V0 experiment budget, not a replacement for the
    contest-wide 120/250 hard caps.  The controller enforces both.
    """

    shield_threshold: float = 0.55
    cut_threshold: float = 0.20
    enable_shield: bool = True
    enable_cut: bool = True
    enable_communicate: bool = True
    p0_exclusive: bool = True
    mixed_raw_roi: bool = False
    max_llm_calls: int = 3
    stop_after_scan: bool = False
    max_steps: int | None = None

    def __post_init__(self) -> None:
        for name in ("shield_threshold", "cut_threshold"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative number")
        if isinstance(self.max_llm_calls, bool) or self.max_llm_calls < 0:
            raise ValueError("max_llm_calls must be a non-negative integer")
        if self.max_steps is not None and (
            isinstance(self.max_steps, bool) or self.max_steps <= 0
        ):
            raise ValueError("max_steps must be a positive integer or None")

    def safety_step_limit(self, node_count: int) -> int:
        """Return the conservative local cap for the current contest tier."""
        if self.max_steps is not None:
            return self.max_steps
        return 115 if node_count <= 50 else 245

    def contest_llm_limit(self, node_count: int) -> int:
        """The public per-seed LLM cap (preliminary/final respectively)."""
        return 120 if node_count <= 50 else 250


DEFAULT_POLICY_CONFIG = PolicyConfig()

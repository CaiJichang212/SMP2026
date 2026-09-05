"""Immutable, auditable switches for V0 policy experiments.

The submission always uses :data:`DEFAULT_POLICY_CONFIG`.  Experiment tools may
pass another instance to ``RuntimeController`` without changing the official
``ParticipantSquadModel(host_env, person_list, llm)`` contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PolicyMode(str, Enum):
    """The only two execution paths exposed to experiments and submission."""

    V0_DETERMINISTIC = "v0_deterministic"
    V1_CMG = "v1_cmg"


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
    # The official default is deliberately a no-LLM V0 baseline.  The old
    # three-call ranking experiment remains available only when opted into.
    max_llm_calls: int = 0
    stop_after_scan: bool = False
    max_steps: int | None = None
    policy_mode: PolicyMode = PolicyMode.V0_DETERMINISTIC
    cmg_cut_limit: int = 64
    cmg_iteration_limit: int = 200
    cmg_convergence_threshold: float = 1e-8
    cmg_planning_seconds: float = 1.0

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
        if not isinstance(self.policy_mode, PolicyMode):
            raise ValueError("policy_mode must be a PolicyMode")
        if isinstance(self.cmg_cut_limit, bool) or self.cmg_cut_limit <= 0:
            raise ValueError("cmg_cut_limit must be a positive integer")
        if isinstance(self.cmg_iteration_limit, bool) or self.cmg_iteration_limit <= 0:
            raise ValueError("cmg_iteration_limit must be a positive integer")
        if self.cmg_convergence_threshold <= 0 or self.cmg_planning_seconds <= 0:
            raise ValueError("CMG thresholds must be positive")

    def safety_step_limit(self, node_count: int) -> int:
        """Return the conservative local cap for the current contest tier."""
        if self.max_steps is not None:
            return self.max_steps
        return 115 if node_count <= 50 else 245

    def contest_llm_limit(self, node_count: int) -> int:
        """The public per-seed LLM cap (preliminary/final respectively)."""
        return 120 if node_count <= 50 else 250


DEFAULT_POLICY_CONFIG = PolicyConfig()

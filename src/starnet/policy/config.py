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
    B1_PERSUASION = "b1_persuasion"
    B2_INFLUENCE = "b2_influence"
    B3_SINGLE_STRUCTURE = "b3_single_structure"
    B4_BEAM_STRUCTURE = "b4_beam_structure"
    B5_ADAPTIVE = "b5_adaptive"
    # Explicitly opt-in experiment mode.  The submission default never
    # selects this value; it is exposed so a separately packaged experiment
    # can be evaluated without weakening B1 fail-closed behavior.
    PUBLIC_GREEDY = "public_greedy"


class LLMSchedule(str, Enum):
    """When the commander may be consulted.

    The gate is independent of ``max_llm_calls``: ``OFF`` is useful for
    deterministic ablations, while ``STEP`` and ``EVENT`` describe when a
    caller may spend an already-authorised call.
    """

    OFF = "off"
    STEP = "step"
    EVENT = "event"


# Friendly aliases used by experiment manifests and older notebooks.
LLMMode = LLMSchedule
LlmSchedule = LLMSchedule


@dataclass(frozen=True)
class PolicyConfig:
    """All V0 tuning knobs, deliberately small and serialisable.

    ``max_llm_calls`` is the V0 experiment budget, not a replacement for the
    contest-wide 120/250 hard caps.  The controller enforces both.
    """

    shield_threshold: float = 0.55
    cut_threshold: float = 0.20
    # P0 is not calibrated: structural actions are off by default and the
    # official submission has no switch that can silently enable them.
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
    # ``None`` means the compatibility default: explicit positive LLM budget
    # opts into STEP, while the ordinary zero-budget configuration is OFF.
    llm_schedule: LLMSchedule | None = None
    structure_depth: int = 2
    structure_width: int = 4
    structure_candidate_limit: int = 12
    # P4 experiment: suppress a communication when the exact same public
    # state already exposes a positive, legal shield alternative.  This is
    # opt-in so prior PUBLIC_GREEDY arms remain reproducible.
    enable_public_comm_shield_guard: bool = False
    adaptive_initial_preliminary: int = 4
    adaptive_initial_final: int = 8

    def __post_init__(self) -> None:
        for name in ("shield_threshold", "cut_threshold"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative number")
        if isinstance(self.max_llm_calls, bool) or not isinstance(self.max_llm_calls, int) or self.max_llm_calls < 0:
            raise ValueError("max_llm_calls must be a non-negative integer")
        if self.max_steps is not None and (
            isinstance(self.max_steps, bool) or self.max_steps <= 0
        ):
            raise ValueError("max_steps must be a positive integer or None")
        if not isinstance(self.policy_mode, PolicyMode):
            raise ValueError("policy_mode must be a PolicyMode")
        if self.llm_schedule is None:
            object.__setattr__(
                self, "llm_schedule",
                LLMSchedule.STEP if self.max_llm_calls > 0 else LLMSchedule.OFF,
            )
        if not isinstance(self.llm_schedule, LLMSchedule):
            raise ValueError("llm_schedule must be an LLMSchedule")
        if not isinstance(self.enable_public_comm_shield_guard, bool):
            raise ValueError("enable_public_comm_shield_guard must be a bool")
        for name in ("structure_depth", "structure_width", "structure_candidate_limit",
                     "adaptive_initial_preliminary", "adaptive_initial_final"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
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
        return 117 if node_count <= 50 else 247

    def contest_llm_limit(self, node_count: int) -> int:
        """The public per-seed LLM cap (preliminary/final respectively)."""
        return 120 if node_count <= 50 else 250


# The only configuration used by the submission: P0 is unverified, therefore
# structural candidate generation and CMG are fail-closed.  ``PolicyConfig``
# itself keeps legacy experiment defaults so historical offline fixtures remain
# reproducible; it is never selected by the submission implicitly.
DEFAULT_POLICY_CONFIG = PolicyConfig(
    enable_shield=False,
    enable_cut=False,
    max_llm_calls=0,
    policy_mode=PolicyMode.B1_PERSUASION,
)

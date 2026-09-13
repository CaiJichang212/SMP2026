from __future__ import annotations

# submission-loader-compat
import sys as _submission_sys
import types as _submission_types

# A conforming import has already registered this module.  The fallback only
# applies to hosts that call ``exec_module`` without doing so first.
if _submission_sys.modules.get(__name__) is None:
    _submission_module = _submission_types.ModuleType(__name__)
    _submission_module.__dict__.update(globals())
    _submission_sys.modules[__name__] = _submission_module

# Begin inline: src/starnet/model/blackboard.py
"""仅保存环境已公开信息的本地黑板。"""


from dataclasses import asdict, dataclass
import math
from typing import Any


Edge = tuple[int, int]


def normalize_edge(left: int, right: int) -> Edge:
    """返回无向边的规范表示；自环不是任务中的有效通信链路。"""
    if left == right:
        raise ValueError("星网边不能连接节点自身")
    return (left, right) if left < right else (right, left)


@dataclass
class NodeState:
    """由一次成功扫描或成功游说得到的节点公开状态。"""

    w: float
    persona: str
    comm_left: int | None

    @classmethod
    def from_scan(cls, payload: dict[str, Any]) -> "NodeState":
        required = {"w", "persona", "neighbors"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"扫描结果缺少字段: {sorted(missing)}")
        raw_w = payload["w"]
        if isinstance(raw_w, bool) or not isinstance(raw_w, (int, float)) or not math.isfinite(raw_w):
            raise ValueError("扫描结果中的 w 必须是有限数值")
        if not isinstance(payload["persona"], str):
            raise ValueError("扫描结果中的 persona 必须是字符串")
        neighbors = payload["neighbors"]
        if not isinstance(neighbors, list) or any(
            isinstance(node_id, bool) or not isinstance(node_id, int) or node_id <= 0
            for node_id in neighbors
        ):
            raise ValueError("扫描结果中的 neighbors 必须是正整数列表")
        raw_comm_left = payload.get("comm_left")
        if raw_comm_left is None:
            comm_left = None
        elif isinstance(raw_comm_left, bool) or not isinstance(raw_comm_left, int):
            raise ValueError("扫描结果中的 comm_left 必须是整数或缺失")
        else:
            comm_left = max(0, raw_comm_left)
        return cls(
            w=float(raw_w),
            persona=payload["persona"],
            comm_left=comm_left,
        )


class Blackboard:
    """Environment facts only, with an append-only action audit trail.

    This deliberately does not contain predictions or LLM prose.  A caller may
    use the snapshot as decision evidence, but every field here must originate
    in an explicit stage contract or a public environment response.
    """

    def __init__(self, node_count: int | None = None) -> None:
        if node_count is not None and (isinstance(node_count, bool) or node_count <= 0):
            raise ValueError("node_count must be a positive integer or None")
        self.node_count = node_count
        self.nodes: dict[int, NodeState] = {}
        self.edges: set[Edge] = set()
        self.dead_nodes: set[int] = set()
        self.shielded_ids: set[int] = set()
        self.nonexistent_ids: set[int] = set()
        self.confirmed_non_edges: set[Edge] = set()
        self.unresolved_nodes: set[int] = set()
        self.budget_units: int | None = None
        self.outer_steps = 0
        self.llm_attempts = 0
        self.env_calls = 0
        self.state_version = 0
        self.events: list[dict[str, Any]] = []

    def can_scan(self, node_id: int) -> bool:
        return (
            node_id > 0
            and (self.node_count is None or node_id <= self.node_count)
            and node_id not in self.nodes
            and node_id not in self.dead_nodes
        )

    @property
    def scanned_ids(self) -> set[int]:
        return set(self.nodes) | set(self.dead_nodes)

    @property
    def frontier_ids(self) -> set[int]:
        return {
            node_id
            for edge in self.edges
            for node_id in edge
            if node_id not in self.scanned_ids and node_id not in self.dead_nodes
        }

    @property
    def unseen_ids(self) -> set[int]:
        if self.node_count is None:
            return set()
        return set(range(1, self.node_count + 1)).difference(self.scanned_ids).difference(self.frontier_ids)

    def set_budget(self, budget: float) -> None:
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget):
            raise ValueError("budget must be a finite number")
        units = round(float(budget) * 2)
        if not math.isclose(float(budget) * 2, units, abs_tol=1e-7):
            raise ValueError("budget must be representable in 0.5 units")
        self.budget_units = max(0, units)

    def record_event(self, kind: str, **data: Any) -> None:
        self.state_version += 1
        self.events.append({"version": self.state_version, "kind": kind, **data})

    def record_scan(self, node_id: int, payload: dict[str, Any] | None) -> bool:
        """写入真实扫描结果；空结果只表示该 ID 当前不可用。"""
        if not self.can_scan(node_id):
            return False
        if payload is None:
            self.dead_nodes.add(node_id)
            self.nonexistent_ids.add(node_id)
            self.record_event("scan", node_id=node_id, status="unavailable")
            return True

        state = NodeState.from_scan(payload)
        self.nodes[node_id] = state
        for neighbor_id in payload["neighbors"]:
            if (
                neighbor_id > 0
                and neighbor_id != node_id
                and (self.node_count is None or neighbor_id <= self.node_count)
            ):
                self.edges.add(normalize_edge(node_id, neighbor_id))
        scanned = set(self.nodes)
        for other_id in scanned.difference({node_id}):
            edge = normalize_edge(node_id, other_id)
            if other_id not in set(payload["neighbors"]):
                self.confirmed_non_edges.add(edge)
        self.record_event("scan", node_id=node_id, status="success")
        return True

    def record_communication(self, node_id: int, response: dict[str, Any]) -> bool:
        """仅在环境报告 success 时更新倾向和可沟通次数。"""
        node = self.nodes.get(node_id)
        if node is None or response.get("status") != "success":
            if node is not None and response.get("status") == "max_comm_reached":
                node.comm_left = 0
                self.record_event("communicate", node_id=node_id, status="max_comm_reached")
            return False
        if "new_w" not in response:
            return False
        node.w = float(response["new_w"])
        raw_comm_left = response.get("comm_left")
        if isinstance(raw_comm_left, int) and not isinstance(raw_comm_left, bool):
            node.comm_left = max(0, raw_comm_left)
        elif node.comm_left is not None:
            node.comm_left = max(0, node.comm_left - 1)
        self.record_event("communicate", node_id=node_id, status="success", new_w=node.w)
        return True

    def record_cut(self, left: int, right: int, success: bool) -> bool:
        if not success:
            return False
        self.edges.discard(normalize_edge(left, right))
        self.record_event("cut", left=left, right=right, status="success")
        return True

    def record_shield(self, node_id: int, success: bool) -> bool:
        if not success or node_id not in self.nodes:
            return False
        del self.nodes[node_id]
        self.edges = {edge for edge in self.edges if node_id not in edge}
        self.dead_nodes.add(node_id)
        self.shielded_ids.add(node_id)
        self.record_event("shield", node_id=node_id, status="success")
        return True

    def snapshot(self) -> dict[str, Any]:
        """为 LLM、日志与回归测试返回可 JSON 序列化的状态快照。"""
        return {
            "nodes": {node_id: asdict(state) for node_id, state in sorted(self.nodes.items())},
            "edges": [list(edge) for edge in sorted(self.edges)],
            "dead_nodes": sorted(self.dead_nodes),
            "shielded_ids": sorted(self.shielded_ids),
            "nonexistent_ids": sorted(self.nonexistent_ids),
            "confirmed_non_edges": [list(edge) for edge in sorted(self.confirmed_non_edges)],
            "frontier_ids": sorted(self.frontier_ids),
            "unseen_ids": sorted(self.unseen_ids),
            "unresolved_nodes": sorted(self.unresolved_nodes),
            "resources": {
                "budget_units": self.budget_units,
                "outer_steps": self.outer_steps,
                "llm_attempts": self.llm_attempts,
                "env_calls": self.env_calls,
            },
            "state_version": self.state_version,
            "events": list(self.events),
        }

# End inline: src/starnet/model/blackboard.py

# Begin inline: src/starnet/policy/actions.py
"""动作预算与合法性校验，不依赖 LLM 或真实环境。"""


from dataclasses import dataclass
from typing import Literal



ActionKind = Literal["scan", "comm", "cut", "shield"]
ACTION_COST: dict[ActionKind, float] = {
    "scan": 0.5,
    "comm": 2.0,
    "cut": 3.0,
    "shield": 5.0,
}
VALID_PROMPT_IDS = frozenset({1, 2, 3})


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target_node_1: int
    target_node_2: int | None = None
    prompt_id: int | None = None


def action_cost(action: Action) -> float:
    return ACTION_COST[action.kind]


def is_legal_action(action: Action, blackboard: Blackboard, budget: float) -> bool:
    """在请求环境前拦截预算不足、未知边和重复动作。"""
    if budget < action_cost(action):
        return False

    node_id = action.target_node_1
    if action.kind == "scan":
        return action.target_node_2 is None and action.prompt_id is None and blackboard.can_scan(node_id)
    if action.kind == "comm":
        node = blackboard.nodes.get(node_id)
        return (
            action.target_node_2 is None
            and node is not None
            and node.comm_left is not None
            and node.comm_left > 0
            and action.prompt_id in VALID_PROMPT_IDS
        )
    if action.kind == "cut":
        if action.target_node_2 is None or action.prompt_id is not None:
            return False
        return normalize_edge(node_id, action.target_node_2) in blackboard.edges
    if action.kind == "shield":
        return action.target_node_2 is None and action.prompt_id is None and node_id in blackboard.nodes
    return False

# End inline: src/starnet/policy/actions.py

# Begin inline: src/starnet/policy/config.py
"""Immutable, auditable switches for V0 policy experiments.

The submission always uses :data:`DEFAULT_POLICY_CONFIG`.  Experiment tools may
pass another instance to ``RuntimeController`` without changing the official
``ParticipantSquadModel(host_env, person_list, llm)`` contract.
"""


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

# End inline: src/starnet/policy/config.py

# Begin inline: src/starnet/policy/calibration.py
"""Frozen, serialisable V1 calibration data.

This module intentionally contains no file I/O.  Offline tools build a
profile, verify its hashes, then copy its literal payload here before a CMG
submission can be enabled.
"""


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
    # Separate qualification for irreversible structure actions.  Keeping it
    # independent from ``gate_passed`` prevents a settlement-only calibration
    # from silently enabling B3/B4.
    structure_gate_passed: bool = False
    structure_action_residual_std: Mapping[str, float] = field(default_factory=dict)
    scenario_gate_passed: bool = False

    def __post_init__(self) -> None:
        if self.model not in {
            "degree",
            "component_degree_plus_one",
            "degroot",
            "friedkin_johnsen",
        }:
            raise ValueError("unknown settlement model")
        for value in (self.rho, self.gamma, self.a, self.b):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("calibration parameters must be finite")
        for values in (self.settlement_residual_std, self.structure_action_residual_std,
                       self.response_mean, self.response_std, self.target_influence):
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

    @property
    def structure_eligible(self) -> bool:
        required = ("comm", "cut", "shield")
        residuals = self.structure_action_residual_std or self.settlement_residual_std
        return (
            self.verified
            and self.structure_gate_passed
            and bool(self.target_influence)
            and all(action in residuals and math.isfinite(float(residuals[action])) for action in required)
        )

    @property
    def scenario_eligible(self) -> bool:
        return self.structure_eligible and self.scenario_gate_passed


# Deliberately fail closed until ``scripts/calibrate_v1.py freeze`` emits a
# reviewed literal profile.  Runtime code never reads experiment artefacts.
DEFAULT_CALIBRATION_PROFILE = CalibrationProfile(gate_passed=False)

# End inline: src/starnet/policy/calibration.py

# Begin inline: src/starnet/policy/baseline.py
"""Conservative P1 persuasion allocation.

No topology action is constructed in this module.  It intentionally works from
the scanned graph only and returns one independently legal communication slot
per eligible node, so a fresh maximum can be selected after every public
response.
"""


from collections.abc import Mapping
import math



_PROMPT_ONE_UNIT_RESPONSE = 15.0
_ONLINE_RESPONSE_PRIOR_WEIGHT = 3.0
# The local response distribution used for the explicit public-greedy
# experiment is r ~ Uniform(0.2, 1.5), so its public first-slot mean is
# 15 * (0.2 + 1.5) / 2 = 12.75.  This is a prior, never an environment field.
_PUBLIC_UNTRIED_RESPONSE_PRIOR = 12.75


def _turn(node_comm_left: int) -> int:
    """Map verified remaining slots to the next 1/2/3 diminishing slot."""
    return 4 - node_comm_left


def _marginal_multiplier(turn: int) -> float:
    """Return the published diminishing multiplier for a legal slot."""
    return {1: 1.0, 2: 0.5, 3: 0.25}.get(turn, 0.0)


def _public_influence_coefficients(blackboard: Blackboard) -> dict[int, float]:
    """Return exact, topology-local communication coefficients for B1.

    The qualified offline settlement relation is linear in an unchanged
    component's opinions::

        |C| / sum_j(degree(j) + 1) * sum_i((degree(i) + 1) * w_i)

    Thus a one-unit successful communication on ``i`` changes its component
    score by the returned coefficient.  This calculation uses only the
    already scanned live graph; it neither predicts an unobserved response nor
    enables a cut or shield action.  In particular, an isolated node has a
    non-zero coefficient (one), unlike the former raw-degree proxy.
    """
    node_ids = set(blackboard.nodes)
    adjacency = {node_id: set() for node_id in node_ids}
    for left, right in blackboard.edges:
        if left in node_ids and right in node_ids:
            adjacency[left].add(right)
            adjacency[right].add(left)

    coefficients: dict[int, float] = {}
    unseen = set(node_ids)
    while unseen:
        start = min(unseen)
        component: list[int] = []
        stack = [start]
        unseen.remove(start)
        while stack:
            node_id = stack.pop()
            component.append(node_id)
            for neighbor in adjacency[node_id]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        denominator = sum(len(adjacency[node_id]) + 1 for node_id in component)
        if denominator <= 0:  # Defensive only; every live node contributes one.
            continue
        scale = len(component) / denominator
        coefficients.update(
            {node_id: scale * (len(adjacency[node_id]) + 1) for node_id in component}
        )
    return coefficients


def _response(
    node_id: int, persona: str, turn: int, responses: Mapping[int, float], profile: CalibrationProfile,
    ledger: ResponseLedger | None = None,
) -> float:
    observed = responses.get(node_id)
    if observed is not None and math.isfinite(observed):
        # The stored observation is always the first successful response for
        # this node.  Later legal slots have the published 1, 1/2, 1/4
        # marginal multiplier; do not rank a repeated persuasion as if it
        # were another first attempt.
        return max(0.0, float(observed)) * _marginal_multiplier(turn)

    # ``responses`` contains only first successful public responses.  With no
    # literal calibrated profile, use their pooled mean for an untried node
    # instead of treating every new target as a one-unit response.  Otherwise
    # the first observed target is spuriously preferred for its second/third
    # slot over every equally promising untried target.  P1 found no persona
    # difference when the response coefficient was controlled, so pooling is
    # both less noisy and avoids encoding a hidden persona/rule assumption.
    # A target's own response above always takes precedence.
    pooled = [float(value) for value in responses.values() if math.isfinite(value)]
    if pooled:
        # The response table establishes +15 for prompt 1 at unit response
        # coefficient.  Three pseudo-observations prevent one unusually high
        # or low first target from immediately steering every untried target;
        # public observations take over quickly as the session progresses.
        return _marginal_multiplier(turn) * max(
            0.0,
            (
                _ONLINE_RESPONSE_PRIOR_WEIGHT * _PROMPT_ONE_UNIT_RESPONSE + sum(pooled)
            ) / (_ONLINE_RESPONSE_PRIOR_WEIGHT + len(pooled)),
        )

    if ledger is not None:
        # A reviewed profile may carry a usable persona-specific prior before
        # this session has any public response.  The default profile does not.
        posterior = ledger.predicted_delta(node_id, persona, 1, profile, turn=turn)
        if posterior is not None and math.isfinite(posterior[0]):
            return max(0.0, float(posterior[0]))
    prior = profile.response_prior(persona, 1, turn) if profile.verified else None
    return max(0.0, prior[0]) if prior is not None else (
        _PROMPT_ONE_UNIT_RESPONSE * _marginal_multiplier(turn)
    )


def public_response(
    node_id: int, persona: str, turn: int, responses: Mapping[int, float],
    profile: CalibrationProfile, ledger: ResponseLedger | None = None,
) -> float:
    """Estimate an experimental slot without pooling unrelated targets.

    ``responses`` stores only a node's first successful public response.  A
    tried node therefore uses its own observed value with the published
    diminishing multiplier.  An untried node uses a fixed population prior;
    one unusually high or low observation must not change every other target's
    expected response.  A verified profile may replace that prior with its
    own held-out response prior, while the unverified public experiment uses
    the fixed 12.75 unit prior above.
    """
    observed = responses.get(node_id)
    if observed is not None and math.isfinite(observed):
        return max(0.0, float(observed)) * _marginal_multiplier(turn)
    if profile.verified:
        prior = profile.response_prior(persona, 1, turn)
        if prior is not None and math.isfinite(prior[0]):
            return max(0.0, float(prior[0]))
    return _PUBLIC_UNTRIED_RESPONSE_PRIOR * _marginal_multiplier(turn)


def persuasion_candidates(
    blackboard: Blackboard,
    budget: float,
    responses: Mapping[int, float],
    profile: CalibrationProfile,
    *,
    use_influence: bool = False,
    failed_actions: frozenset[str] | set[str] = frozenset(),
    ledger: ResponseLedger | None = None,
) -> list[Candidate]:
    """Return stable B1/B2 communication candidates with non-negative gain.

    B1 multiplies a response estimate by an exact coefficient from the public,
    scanned connected component. B2 may replace that coefficient only when the
    frozen calibration profile contains a held-out target coefficient. Missing
    coefficients fail back to B1; a caller must not claim a B2 result in that
    case.
    """
    result: list[Candidate] = []
    public_influence = _public_influence_coefficients(blackboard)
    for node_id, node in sorted(blackboard.nodes.items()):
        if node.comm_left is None or node.comm_left <= 0:
            continue
        turn = _turn(node.comm_left)
        if turn not in (1, 2, 3):
            continue
        action = Action("comm", node_id, prompt_id=1)
        candidate_id = f"comm:{node_id}:{turn}"
        if candidate_id in failed_actions:
            continue
        if not is_legal_action(action, blackboard, budget):
            continue
        response = _response(node_id, node.persona, turn, responses, profile, ledger)
        coefficient = public_influence.get(node_id, 0.0)
        reason = "public component influence"
        if use_influence:
            raw_h = profile.target_influence.get(str(node_id))
            if raw_h is not None and math.isfinite(float(raw_h)):
                coefficient = max(0.0, float(raw_h))
                reason = "held-out influence"
        gain = coefficient * response
        if gain <= 0.0:
            continue
        result.append(
            Candidate(
                candidate_id=candidate_id,
                action=action,
                priority=0,
                score=gain,
                roi=gain / action_cost(action),
                reason=reason + f" × response, slot {turn}",
            )
        )
    return sorted(result, key=lambda item: (-item.roi, item.candidate_id))


__all__ = ["persuasion_candidates", "public_response"]

# End inline: src/starnet/policy/baseline.py

# Begin inline: src/starnet/runtime/env_adapter.py
"""环境调用的单一入口：只使用赛题公开 API，并以返回值更新黑板。"""


from dataclasses import dataclass
from typing import Any, Protocol



class StarNetEnvironment(Protocol):
    def scan_node(self, node_id: int) -> dict[str, Any] | None: ...
    def communicate(self, node_id: int, prompt_id: int) -> dict[str, Any] | None: ...
    def cut_link(self, left: int, right: int) -> bool | None: ...
    def shield_node(self, node_id: int) -> bool | None: ...


@dataclass(frozen=True)
class ActionOutcome:
    """Detailed result of one public environment action.

    ``raw_response`` is intentionally preserved for a local trace.  It is not
    interpreted beyond the existing Blackboard update rules and is never
    emitted by the submission unless an external caller attaches a trace.
    """

    action: Action
    succeeded: bool
    raw_response: Any = None
    rejected_reason: str | None = None


def apply_action_outcome(
    env: StarNetEnvironment, blackboard: Blackboard, action: Action, budget: float
) -> ActionOutcome:
    """Run one legal action and retain the raw public response for diagnostics."""
    if not is_legal_action(action, blackboard, budget):
        return ActionOutcome(action=action, succeeded=False, rejected_reason="illegal_action")

    if action.kind == "scan":
        response = env.scan_node(action.target_node_1)
        return ActionOutcome(
            action=action,
            succeeded=blackboard.record_scan(action.target_node_1, response),
            raw_response=response,
        )
    if action.kind == "comm":
        assert action.prompt_id is not None
        response = env.communicate(action.target_node_1, action.prompt_id)
        if not isinstance(response, dict):
            return ActionOutcome(action=action, succeeded=False, raw_response=response)
        return ActionOutcome(
            action=action,
            succeeded=blackboard.record_communication(action.target_node_1, response),
            raw_response=response,
        )
    if action.kind == "cut":
        assert action.target_node_2 is not None
        response = env.cut_link(action.target_node_1, action.target_node_2)
        return ActionOutcome(
            action=action,
            succeeded=blackboard.record_cut(action.target_node_1, action.target_node_2, response),
            raw_response=response,
        )
    if action.kind == "shield":
        response = env.shield_node(action.target_node_1)
        return ActionOutcome(
            action=action,
            succeeded=blackboard.record_shield(action.target_node_1, response),
            raw_response=response,
        )
    return ActionOutcome(action=action, succeeded=False, rejected_reason="unknown_action")


def apply_action(
    env: StarNetEnvironment, blackboard: Blackboard, action: Action, budget: float
) -> bool:
    """执行已校验动作；失败路径不虚构状态，也不访问环境私有成员。"""
    return apply_action_outcome(env, blackboard, action, budget).succeeded


__all__ = ["ActionOutcome", "StarNetEnvironment", "apply_action", "apply_action_outcome"]

# End inline: src/starnet/runtime/env_adapter.py

# Begin inline: src/starnet/runtime/trace.py
"""Best-effort structured diagnostics for local StarNet runs.

The trace is deliberately a side channel: a failed sink is disabled and never
allowed to affect controller decisions or environment calls.  Submission code
does not create a trace; local tools inject one before the first ``step``.
"""


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

# End inline: src/starnet/runtime/trace.py

# Begin inline: src/starnet/policy/graph_analysis.py
"""Deterministic NetworkX-derived graph metrics for the intervention policy.

The blackboard remains the source of truth. This module only creates a fresh
read model of its scanned, live nodes for scoring and candidate generation.
"""


from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping, TypeVar

import networkx as nx



MetricKey = TypeVar("MetricKey")


@dataclass(frozen=True)
class NodeMetrics:
    """Normalized structural and policy scores for one scanned live node."""

    degree: float
    pagerank: float
    core: float
    betweenness: float
    voterank: float
    influence: float
    positive_influence: float
    danger: float
    community_id: int


@dataclass(frozen=True)
class EdgeMetrics:
    """Normalized structural and negative-flow scores for one live edge."""

    edge_betweenness: float
    cross_community: bool
    negative_flow: float


@dataclass(frozen=True)
class GraphAnalysis:
    """Read-only metrics consumed by the candidate-generation policy.

    ``node_metrics`` is keyed by node ID and ``edge_metrics`` by normalized
    ``(min_node_id, max_node_id)`` edges. Candidate generation should consult
    the blackboard again before producing or executing an action.
    """

    graph: nx.Graph
    node_metrics: Mapping[int, NodeMetrics]
    edge_metrics: Mapping[Edge, EdgeMetrics]
    community_count: int

    @property
    def nodes(self) -> Mapping[int, NodeMetrics]:
        """Short alias for callers that only need node metrics."""
        return self.node_metrics

    @property
    def edges(self) -> Mapping[Edge, EdgeMetrics]:
        """Short alias for callers that only need edge metrics."""
        return self.edge_metrics

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()


def stable_normalize(values: Mapping[MetricKey, float]) -> dict[MetricKey, float]:
    """Min-max normalize scores without NaN, division-by-zero, or tie drift.

    An all-zero feature stays zero. A constant, non-zero feature is retained as
    one for every element so structurally equivalent positive signals are not
    accidentally erased.
    """
    if not values:
        return {}

    cleaned = {
        key: float(value) if math.isfinite(float(value)) else 0.0
        for key, value in values.items()
    }
    minimum = min(cleaned.values())
    maximum = max(cleaned.values())
    if minimum == maximum:
        constant = 0.0 if maximum == 0.0 else 1.0
        return {key: constant for key in values}

    span = maximum - minimum
    return {
        key: min(1.0, max(0.0, (cleaned[key] - minimum) / span))
        for key in values
    }


def build_graph(blackboard: Blackboard) -> nx.Graph:
    """Build a deterministic, derived graph from known live blackboard state."""
    graph = nx.Graph()
    live_nodes = sorted(blackboard.nodes)
    graph.add_nodes_from(live_nodes)

    live_node_set = set(live_nodes)
    for left, right in sorted(blackboard.edges):
        edge = normalize_edge(left, right)
        if edge[0] in live_node_set and edge[1] in live_node_set:
            graph.add_edge(*edge)
    return graph


def _deterministic_pagerank(graph: nx.Graph) -> dict[int, float]:
    """Run PageRank with a pure-Python fallback when NetworkX lacks numpy."""
    nodes = list(graph.nodes)
    if not nodes:
        return {}

    try:
        scores = nx.pagerank(graph, alpha=0.85, max_iter=1_000, tol=1.0e-12)
        return {node: float(scores[node]) for node in nodes}
    except (ImportError, ModuleNotFoundError, nx.PowerIterationFailedConvergence):
        pass

    # NetworkX's default implementation needs an optional numerical backend in
    # some supported versions. This is the same undirected random-walk update.
    node_count = len(nodes)
    alpha = 0.85
    scores = {node: 1.0 / node_count for node in nodes}
    for _ in range(1_000):
        dangling_mass = sum(scores[node] for node in nodes if graph.degree(node) == 0)
        updated: dict[int, float] = {}
        for node in nodes:
            inbound = sum(
                scores[neighbor] / graph.degree(neighbor)
                for neighbor in graph.neighbors(node)
            )
            updated[node] = (1.0 - alpha) / node_count + alpha * (
                inbound + dangling_mass / node_count
            )
        if sum(abs(updated[node] - scores[node]) for node in nodes) < 1.0e-12:
            return updated
        scores = updated
    return scores


def _communities(graph: nx.Graph) -> tuple[dict[int, int], int]:
    """Return stable community IDs, including isolated vertices."""
    if not graph.nodes:
        return {}, 0
    if graph.number_of_edges() == 0:
        groups = [{node} for node in graph.nodes]
    else:
        groups = [set(group) for group in nx.community.greedy_modularity_communities(graph)]

    groups.sort(key=lambda group: min(group))
    community_ids = {
        node: community_id
        for community_id, group in enumerate(groups)
        for node in sorted(group)
    }
    return community_ids, len(groups)


def _voterank_scores(graph: nx.Graph) -> dict[int, float]:
    """Convert NetworkX VoteRank's deterministic ordering to reciprocal ranks."""
    scores = {node: 0.0 for node in graph.nodes}
    for position, node in enumerate(nx.voterank(graph), start=1):
        scores[node] = 1.0 / position
    return scores


def _negative_strengths(blackboard: Blackboard, nodes: list[int]) -> dict[int, float]:
    raw = {node: max(-blackboard.nodes[node].w, 0.0) for node in nodes}
    maximum = max(raw.values(), default=0.0)
    if maximum == 0.0:
        return {node: 0.0 for node in nodes}
    return {node: raw[node] / maximum for node in nodes}


def _persona_prior(persona: str) -> float:
    return {"和平": 1.0, "中立": 0.7, "暴力": 0.0}.get(persona, 0.0)


def _persona_risk(persona: str) -> float:
    return {"暴力": 1.0, "中立": 0.5, "和平": 0.25}.get(persona, 0.5)


def _marginal_factor(comm_left: int | None) -> float:
    return {3: 1.0, 2: 0.5, 1: 0.25}.get(comm_left, 0.0)


def analyze_graph(blackboard: Blackboard) -> GraphAnalysis:
    """Compute deterministic structure, influence, danger, and edge metrics."""
    graph = build_graph(blackboard)
    nodes = list(graph.nodes)
    if not nodes:
        return GraphAnalysis(
            graph=graph,
            node_metrics=MappingProxyType({}),
            edge_metrics=MappingProxyType({}),
            community_count=0,
        )

    degree = stable_normalize(nx.degree_centrality(graph))
    pagerank = stable_normalize(_deterministic_pagerank(graph))
    core = stable_normalize(nx.core_number(graph))
    betweenness = stable_normalize(nx.betweenness_centrality(graph, normalized=True))
    # Reciprocal VoteRank is already in [0, 1]; applying min-max normalization
    # would destroy the specified 1 / rank semantics.
    voterank = _voterank_scores(graph)
    community_ids, community_count = _communities(graph)
    negative_strength = _negative_strengths(blackboard, nodes)

    node_metrics: dict[int, NodeMetrics] = {}
    for node in nodes:
        state = blackboard.nodes[node]
        influence = (
            0.25 * degree[node]
            + 0.25 * pagerank[node]
            + 0.20 * core[node]
            + 0.20 * betweenness[node]
            + 0.10 * voterank[node]
        )
        positive_influence = influence * _persona_prior(state.persona) * _marginal_factor(state.comm_left)
        danger = negative_strength[node] * _persona_risk(state.persona) * (
            0.70 * influence + 0.30 * betweenness[node]
        )
        node_metrics[node] = NodeMetrics(
            degree=degree[node],
            pagerank=pagerank[node],
            core=core[node],
            betweenness=betweenness[node],
            voterank=voterank[node],
            influence=min(1.0, max(0.0, influence)),
            positive_influence=min(1.0, max(0.0, positive_influence)),
            danger=min(1.0, max(0.0, danger)),
            community_id=community_ids[node],
        )

    raw_edge_betweenness = {
        normalize_edge(left, right): score
        for (left, right), score in nx.edge_betweenness_centrality(graph, normalized=True).items()
    }
    edge_betweenness = stable_normalize(raw_edge_betweenness)
    edge_metrics: dict[Edge, EdgeMetrics] = {}
    for edge in sorted(graph.edges):
        left, right = normalize_edge(*edge)
        left_metrics = node_metrics[left]
        right_metrics = node_metrics[right]
        negative_flow = max(
            left_metrics.danger * (1.0 - negative_strength[right]),
            right_metrics.danger * (1.0 - negative_strength[left]),
        )
        edge_metrics[(left, right)] = EdgeMetrics(
            edge_betweenness=edge_betweenness[(left, right)],
            cross_community=left_metrics.community_id != right_metrics.community_id,
            negative_flow=min(1.0, max(0.0, negative_flow)),
        )

    return GraphAnalysis(
        graph=graph,
        node_metrics=MappingProxyType(node_metrics),
        edge_metrics=MappingProxyType(edge_metrics),
        community_count=community_count,
    )


__all__ = [
    "EdgeMetrics",
    "GraphAnalysis",
    "NodeMetrics",
    "analyze_graph",
    "build_graph",
    "stable_normalize",
]

# End inline: src/starnet/policy/graph_analysis.py

# Begin inline: src/starnet/policy/candidates.py
"""候选生成与不依赖 LLM 的批次选择。"""


import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any



MAX_PRIORITY_CANDIDATES: dict[int, int] = {0: 4, 1: 4, 2: 8}
MAX_CANDIDATES = 12
MAX_BATCH_SIZE = 10
VALID_BATCH_MODES = frozenset({"risk_first", "growth_first", "balanced"})


@dataclass(frozen=True)
class Candidate:
    """一个已经由 Python 验证过的环境动作。"""

    candidate_id: str
    action: Action
    priority: int
    score: float
    roi: float
    reason: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LlmParseResult:
    """Validated LLM selection and the observable reason for any fallback."""

    candidate_ids: tuple[str, ...]
    accepted: bool
    fallback_reason: str | None = None


def _candidate_sort_key(
    candidate: Candidate, *, mixed_raw_roi: bool = False
) -> tuple[int, float, float, str]:
    """计划规定的稳定候选排序。"""
    return (
        0 if mixed_raw_roi else candidate.priority,
        -_finite_nonnegative(candidate.roi),
        action_cost(candidate.action),
        candidate.candidate_id,
    )


def _finite_nonnegative(value: float) -> float:
    return value if math.isfinite(value) and value >= 0.0 else 0.0


def _is_failed(candidate_id: str, action: Action, failed_actions: Iterable[object]) -> bool:
    """接受控制器按候选 ID 或 Action 记录的失败集合。"""
    return candidate_id in failed_actions or action in failed_actions


def _eligible(
    candidate_id: str,
    action: Action,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object],
) -> bool:
    return not _is_failed(candidate_id, action, failed_actions) and is_legal_action(
        action, blackboard, budget
    )


def _node_metric(analysis: GraphAnalysis, node_id: int) -> NodeMetrics | None:
    return analysis.node_metrics.get(node_id)


def _shield_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object],
    config: PolicyConfig,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for node_id, node in sorted(blackboard.nodes.items()):
        metrics = _node_metric(analysis, node_id)
        if metrics is None or node.persona != "暴力" or node.w >= 0.0:
            continue
        danger = _finite_nonnegative(metrics.danger)
        if danger < config.shield_threshold:
            continue
        action = Action("shield", node_id)
        candidate_id = f"shield:{node_id}"
        if not _eligible(candidate_id, action, blackboard, budget, failed_actions):
            continue
        candidates.append(
            Candidate(
                candidate_id=candidate_id,
                action=action,
                priority=0,
                score=danger,
                roi=danger / action_cost(action),
                reason=f"high-risk violent node (danger={danger:.3f})",
            )
        )
    return sorted(
        candidates,
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )[:MAX_PRIORITY_CANDIDATES[0]]


def _is_negative_bridge(
    left: NodeState,
    right: NodeState,
    left_metrics: NodeMetrics,
    right_metrics: NodeMetrics,
    edge_metrics: EdgeMetrics,
) -> bool:
    """返回是否存在从高风险端流向非暴力或非负端的传播风险。"""
    if not edge_metrics.cross_community:
        return False

    left_danger = _finite_nonnegative(left_metrics.danger)
    right_danger = _finite_nonnegative(right_metrics.danger)
    return (
        left_danger > 0.0 and (right.persona != "暴力" or right.w >= 0.0)
    ) or (
        right_danger > 0.0 and (left.persona != "暴力" or left.w >= 0.0)
    )


def _cut_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object],
    config: PolicyConfig,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for edge, edge_metrics in sorted(analysis.edge_metrics.items()):
        left_id, right_id = normalize_edge(*edge)
        normalized_edge: Edge = (left_id, right_id)
        left = blackboard.nodes.get(left_id)
        right = blackboard.nodes.get(right_id)
        left_metrics = _node_metric(analysis, left_id)
        right_metrics = _node_metric(analysis, right_id)
        if (
            left is None
            or right is None
            or left_metrics is None
            or right_metrics is None
            or normalized_edge not in blackboard.edges
            or not _is_negative_bridge(left, right, left_metrics, right_metrics, edge_metrics)
        ):
            continue

        cut_score = _finite_nonnegative(edge_metrics.negative_flow) * _finite_nonnegative(
            edge_metrics.edge_betweenness
        )
        if cut_score < config.cut_threshold:
            continue
        action = Action("cut", left_id, target_node_2=right_id)
        candidate_id = f"cut:{left_id}-{right_id}"
        if not _eligible(candidate_id, action, blackboard, budget, failed_actions):
            continue
        candidates.append(
            Candidate(
                candidate_id=candidate_id,
                action=action,
                priority=1,
                score=cut_score,
                roi=cut_score / action_cost(action),
                reason=f"cross-community negative bridge (score={cut_score:.3f})",
            )
        )
    return sorted(
        candidates,
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )[:MAX_PRIORITY_CANDIDATES[1]]


def _communicate_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object],
    config: PolicyConfig,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for node_id, node in sorted(blackboard.nodes.items()):
        metrics = _node_metric(analysis, node_id)
        if metrics is None or node.persona not in {"和平", "中立"}:
            continue
        positive = _finite_nonnegative(metrics.positive_influence)
        if positive <= 0.0:
            continue
        action = Action("comm", node_id, prompt_id=1)
        candidate_id = f"comm:{node_id}:1"
        if not _eligible(candidate_id, action, blackboard, budget, failed_actions):
            continue
        candidates.append(
            Candidate(
                candidate_id=candidate_id,
                action=action,
                priority=2,
                score=positive,
                roi=positive / action_cost(action),
                reason=f"positive influence target (score={positive:.3f})",
            )
        )
    return sorted(
        candidates,
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )[:MAX_PRIORITY_CANDIDATES[2]]


def generate_candidates(
    analysis: GraphAnalysis,
    blackboard: Blackboard,
    budget: float,
    failed_actions: Iterable[object] = (),
    config: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> list[Candidate]:
    """从当前黑板和图指标生成稳定、已校验的候选集。

    P0 出现时，本轮只暴露 P0。拓扑或节点状态改变后的下一轮会重新生成 P1/P2，
    因此高危屏蔽不会被普通增益动作延后。
    """
    failed = frozenset(failed_actions)
    shields = (
        _shield_candidates(analysis, blackboard, budget, failed, config)
        if config.enable_shield
        else []
    )
    if shields and config.p0_exclusive:
        return shields[:MAX_CANDIDATES]

    cuts = (
        _cut_candidates(analysis, blackboard, budget, failed, config)
        if config.enable_cut
        else []
    )
    communications = (
        _communicate_candidates(analysis, blackboard, budget, failed, config)
        if config.enable_communicate
        else []
    )
    candidates = shields + cuts + communications
    return sorted(
        candidates,
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )[:MAX_CANDIDATES]


def _conflicts(action: Action, selected_actions: Iterable[Action]) -> bool:
    """shield 与连接该节点的 cut 不能出现在同一批次。"""
    for selected in selected_actions:
        shield, cut = (action, selected) if action.kind == "shield" else (selected, action)
        if (
            shield.kind == "shield"
            and cut.kind == "cut"
            and shield.target_node_1 in {cut.target_node_1, cut.target_node_2}
        ):
            return True
    return False


def _valid_batch_ids(
    candidate_ids: Iterable[object],
    candidate_map: Mapping[str, Candidate],
    budget: float,
    limit: int,
) -> list[str]:
    """按给定顺序保留候选存在、非重复、无冲突且预算充足的前缀。"""
    selected_ids: list[str] = []
    selected_actions: list[Action] = []
    remaining_budget = max(0.0, float(budget))
    for candidate_id in candidate_ids:
        if not isinstance(candidate_id, str) or candidate_id in selected_ids:
            continue
        candidate = candidate_map.get(candidate_id)
        if candidate is None or len(selected_ids) >= limit:
            continue
        cost = action_cost(candidate.action)
        if cost > remaining_budget or _conflicts(candidate.action, selected_actions):
            continue
        selected_ids.append(candidate_id)
        selected_actions.append(candidate.action)
        remaining_budget -= cost
    return selected_ids


def select_deterministic_batch(
    candidates: Iterable[Candidate], budget: float, limit: int = MAX_BATCH_SIZE,
    *, config: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> list[str]:
    """规则回退：按稳定优先级取预算内、互不冲突的动作。"""
    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    ordered = sorted(
        candidate_map.values(),
        key=lambda item: _candidate_sort_key(item, mixed_raw_roi=config.mixed_raw_roi),
    )
    return _valid_batch_ids(
        (candidate.candidate_id for candidate in ordered),
        candidate_map,
        budget,
        min(max(0, limit), MAX_BATCH_SIZE),
    )


def parse_llm_batch(
    payload: str | bytes | Mapping[str, Any] | None,
    candidate_map: Mapping[str, Candidate],
    budget: float,
    *,
    config: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> list[str]:
    """解析 Commander 的 JSON；任意无效或空结果均回退到确定性批次。"""
    return list(parse_llm_batch_detailed(payload, candidate_map, budget, config=config).candidate_ids)


def parse_llm_batch_detailed(
    payload: str | bytes | Mapping[str, Any] | None,
    candidate_map: Mapping[str, Candidate],
    budget: float,
    *,
    config: PolicyConfig = DEFAULT_POLICY_CONFIG,
) -> LlmParseResult:
    """Parse a Commander result while retaining a precise fallback category."""
    fallback = select_deterministic_batch(candidate_map.values(), budget, config=config)
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return LlmParseResult(tuple(fallback), False, "invalid_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return LlmParseResult(tuple(fallback), False, "invalid_json")
    if not isinstance(payload, Mapping):
        return LlmParseResult(tuple(fallback), False, "invalid_json")

    mode = payload.get("mode")
    candidate_ids = payload.get("candidate_ids")
    if mode not in VALID_BATCH_MODES or not isinstance(candidate_ids, list):
        return LlmParseResult(tuple(fallback), False, "invalid_json")
    if not candidate_ids:
        return LlmParseResult(tuple(fallback), False, "empty_selection")

    selected = _valid_batch_ids(candidate_ids, candidate_map, budget, MAX_BATCH_SIZE)
    if selected:
        return LlmParseResult(tuple(selected), True)
    known_ids = [candidate_id for candidate_id in candidate_ids if isinstance(candidate_id, str)]
    reason = "unknown_candidate" if not any(candidate_id in candidate_map for candidate_id in known_ids) else "empty_selection"
    return LlmParseResult(tuple(fallback), False, reason)


__all__ = [
    "Candidate",
    "LlmParseResult",
    "MAX_BATCH_SIZE",
    "MAX_CANDIDATES",
    "VALID_BATCH_MODES",
    "generate_candidates",
    "parse_llm_batch",
    "parse_llm_batch_detailed",
    "select_deterministic_batch",
]

# End inline: src/starnet/policy/candidates.py

# Begin inline: src/starnet/policy/cmg.py
"""Pure response-aware conservative marginal-gain planning for V1."""


from dataclasses import dataclass, field
import math
import time
from typing import Iterable

import networkx as nx



class CMGPlanningError(RuntimeError):
    """A fail-closed prediction or time-budget failure."""


@dataclass
class ResponseLedger:
    """Online posterior keyed by ``persona × prompt × turn``.

    A node's own successful response sequence is preferred.  Until that exists,
    the posterior is pooled by the exact calibration key, then falls back to
    the frozen calibration prior.
    """

    successful_comm_count: dict[int, int] = field(default_factory=dict)
    observed_deltas: dict[int, list[float]] = field(default_factory=dict)
    first_delta: dict[int, float] = field(default_factory=dict)
    last_w: dict[int, float] = field(default_factory=dict)
    posterior_count: dict[str, int] = field(default_factory=dict)
    posterior_mean: dict[str, float] = field(default_factory=dict)
    posterior_m2: dict[str, float] = field(default_factory=dict)

    def record_success(
        self, node_id: int, before_w: float, new_w: float,
        *, persona: str | None = None, prompt_id: int = 1, turn: int | None = None,
    ) -> None:
        delta = float(new_w) - float(before_w)
        if not math.isfinite(delta):
            raise CMGPlanningError("nonfinite_response")
        values = self.observed_deltas.setdefault(node_id, [])
        values.append(delta)
        self.successful_comm_count[node_id] = len(values)
        self.first_delta.setdefault(node_id, delta)
        self.last_w[node_id] = float(new_w)
        if persona is not None and turn in (1, 2, 3):
            key = CalibrationProfile.response_key(persona, prompt_id, turn)
            count = self.posterior_count.get(key, 0) + 1
            old_mean = self.posterior_mean.get(key, 0.0)
            difference = delta - old_mean
            mean = old_mean + difference / count
            self.posterior_count[key] = count
            self.posterior_mean[key] = mean
            self.posterior_m2[key] = self.posterior_m2.get(key, 0.0) + difference * (delta - mean)

    def predicted_delta(
        self, node_id: int, persona: str, prompt_id: int, profile: CalibrationProfile,
        turn: int | None = None,
    ) -> tuple[float, float] | None:
        count = self.successful_comm_count.get(node_id, 0)
        if count == 0:
            return self.posterior_for(persona, prompt_id, turn or 1, profile)
        first = self.first_delta.get(node_id)
        if first is None:
            return None
        # The copied predictive state may include further hypothetical slots
        # beyond the real ledger.  Honour its actual slot number when given;
        # without one preserve the historical "next observed slot" API.
        target_turn = turn if turn in (1, 2, 3) else count + 1
        if target_turn == 2:
            return first * 0.5, 0.0
        if target_turn == 3:
            return first * 0.25, 0.0
        return None

    def posterior_for(
        self, persona: str, prompt_id: int, turn: int, profile: CalibrationProfile
    ) -> tuple[float, float] | None:
        """Return the observed group posterior, or the calibrated prior."""
        key = CalibrationProfile.response_key(persona, prompt_id, turn)
        count = self.posterior_count.get(key, 0)
        if count:
            mean = self.posterior_mean[key]
            variance = self.posterior_m2.get(key, 0.0) / max(1, count - 1)
            return mean, math.sqrt(max(0.0, variance))
        return profile.response_prior(persona, prompt_id, turn)


@dataclass(frozen=True)
class PredictiveState:
    """A copied public state used for hypothetical actions only."""

    nodes: dict[int, NodeState]
    edges: set[tuple[int, int]]
    dead_nodes: set[int]

    @classmethod
    def from_blackboard(cls, board: Blackboard) -> "PredictiveState":
        return cls(
            nodes={node_id: NodeState(node.w, node.persona, node.comm_left) for node_id, node in board.nodes.items()},
            edges=set(board.edges),
            dead_nodes=set(board.dead_nodes),
        )

    def to_blackboard(self) -> Blackboard:
        board = Blackboard()
        board.nodes = {node_id: NodeState(node.w, node.persona, node.comm_left) for node_id, node in self.nodes.items()}
        board.edges = set(self.edges)
        board.dead_nodes = set(self.dead_nodes)
        return board

    def apply(self, action: Action, comm_delta: float | None = None) -> "PredictiveState":
        # This method is called for every structural counterfactual.  Copy the
        # three public-state containers directly instead of constructing a
        # Blackboard, recording an event, and converting it back each time.
        # The resulting state is identical but avoids substantial allocator
        # and event-list churn on 100-node beam searches.
        nodes = {node_id: NodeState(node.w, node.persona, node.comm_left) for node_id, node in self.nodes.items()}
        edges = set(self.edges)
        dead_nodes = set(self.dead_nodes)
        if action.kind == "comm":
            if comm_delta is None or action.target_node_1 not in nodes:
                raise CMGPlanningError("invalid_hypothesis")
            nodes[action.target_node_1].w += comm_delta
            if nodes[action.target_node_1].comm_left is not None:
                nodes[action.target_node_1].comm_left = max(0, nodes[action.target_node_1].comm_left - 1)
        elif action.kind == "cut":
            if action.target_node_2 is None:
                raise CMGPlanningError("invalid_hypothesis")
            edges.discard(tuple(sorted((action.target_node_1, action.target_node_2))))
        elif action.kind == "shield":
            if action.target_node_1 not in nodes:
                raise CMGPlanningError("invalid_hypothesis")
            del nodes[action.target_node_1]
            dead_nodes.add(action.target_node_1)
            edges = {edge for edge in edges if action.target_node_1 not in edge}
        else:
            raise CMGPlanningError("invalid_hypothesis")
        return PredictiveState(nodes, edges, dead_nodes)


@dataclass(frozen=True)
class ScoredCandidate:
    candidate_id: str
    action: Action
    score_before: float
    score_after: float
    gain: float
    sigma: float
    lcb_roi: float
    response_delta: float | None = None


class SettlementPredictor:
    """The three preregistered offline settlement model families."""

    def __init__(self, profile: CalibrationProfile, *, iterations: int = 200, threshold: float = 1e-8) -> None:
        self.profile = profile
        self.iterations = iterations
        self.threshold = threshold

    def score(self, state: PredictiveState) -> float:
        nodes = sorted(state.nodes)
        if not nodes:
            return 0.0
        if self.profile.model == "component_degree_plus_one":
            # Keep the verified formula exactly, but avoid constructing a
            # NetworkX graph for every hypothetical state.  This is the hot
            # path in B4 and is materially cheaper and smaller on 100-node
            # graphs under the 4-GiB experiment limit.
            parent = {node: node for node in nodes}
            degree = {node: 0 for node in nodes}

            def find(node: int) -> int:
                root = node
                while parent[root] != root:
                    root = parent[root]
                while parent[node] != node:
                    next_node = parent[node]
                    parent[node] = root
                    node = next_node
                return root

            def union(left: int, right: int) -> None:
                left_root, right_root = find(left), find(right)
                if left_root != right_root:
                    parent[right_root] = left_root

            for left, right in state.edges:
                if left in degree and right in degree:
                    degree[left] += 1
                    degree[right] += 1
                    union(left, right)
            totals: dict[int, tuple[int, float, int]] = {}
            for node in nodes:
                root = find(node)
                factor = degree[node] + 1
                size, weighted, denominator = totals.get(root, (0, 0.0, 0))
                totals[root] = (size + 1, weighted + factor * float(state.nodes[node].w), denominator + factor)
            return sum(size * weighted / denominator for size, weighted, denominator in totals.values())
        graph = nx.Graph()
        graph.add_nodes_from(nodes)
        graph.add_edges_from(edge for edge in state.edges if edge[0] in state.nodes and edge[1] in state.nodes)
        weights = {node: float(state.nodes[node].w) for node in nodes}
        if not all(math.isfinite(value) for value in weights.values()):
            raise CMGPlanningError("nonfinite_state")
        if self.profile.model == "degree":
            return sum(max(1, graph.degree(node)) * weights[node] for node in nodes)
        transition = self._transition(graph, nodes)
        if self.profile.model == "degroot":
            settled = self._iterate(transition, weights)
        else:
            n_minus_one = max(1, len(nodes) - 1)
            retain = {node: min(1.0, max(0.0, self.profile.a + self.profile.b * graph.degree(node) / n_minus_one)) for node in nodes}
            settled = self._iterate(transition, weights, retain)
        return sum(max(1, graph.degree(node)) * settled[node] for node in nodes)

    def _transition(self, graph: nx.Graph, nodes: list[int]) -> dict[int, dict[int, float]]:
        result: dict[int, dict[int, float]] = {}
        for node in nodes:
            degree = graph.degree(node)
            row = {node: 1.0 + self.profile.rho * degree}
            for neighbor in graph.neighbors(node):
                row[neighbor] = max(1, graph.degree(neighbor)) ** self.profile.gamma
            total = sum(row.values())
            if not math.isfinite(total) or total <= 0:
                raise CMGPlanningError("invalid_transition")
            result[node] = {target: value / total for target, value in row.items()}
        return result

    def _iterate(
        self, transition: dict[int, dict[int, float]], initial: dict[int, float], retain: dict[int, float] | None = None
    ) -> dict[int, float]:
        current = dict(initial)
        for _ in range(self.iterations):
            following: dict[int, float] = {}
            for node, row in transition.items():
                mixed = sum(weight * current[target] for target, weight in row.items())
                following[node] = mixed if retain is None else retain[node] * initial[node] + (1.0 - retain[node]) * mixed
            if not all(math.isfinite(value) for value in following.values()):
                raise CMGPlanningError("nonfinite_prediction")
            if max(abs(following[node] - current[node]) for node in current) <= self.threshold:
                return following
            current = following
        raise CMGPlanningError("nonconvergent")


def _cmg_cut_candidates(board: Blackboard, limit: int) -> list[Action]:
    edges = sorted(board.edges)
    if len(edges) <= limit:
        return [Action("cut", left, target_node_2=right) for left, right in edges]
    analysis = analyze_graph(board)
    graph = analysis.graph
    scores: list[tuple[float, str, Action]] = []
    max_negative = max((max(0.0, -node.w) for node in board.nodes.values()), default=0.0) or 1.0
    max_influence = max((metrics.positive_influence for metrics in analysis.node_metrics.values()), default=0.0) or 1.0
    for left, right in edges:
        left_state, right_state = board.nodes[left], board.nodes[right]
        metrics = analysis.edge_metrics.get((left, right))
        betweenness = metrics.edge_betweenness if metrics else 0.0
        cross = 1.0 if metrics and metrics.cross_community else 0.0
        endpoint_influence = max(analysis.node_metrics[left].positive_influence, analysis.node_metrics[right].positive_influence)
        score = 0.5 * max(max(0.0, -left_state.w), max(0.0, -right_state.w)) / max_negative
        score += 0.25 * endpoint_influence / max_influence
        score += 0.25 * (betweenness + cross) / 2.0
        action = Action("cut", left, target_node_2=right)
        scores.append((-score, f"cut:{left}-{right}", action))
    return [item[2] for item in sorted(scores)[:limit]]


def enumerate_cmg_actions(board: Blackboard, budget: float, cut_limit: int) -> list[Action]:
    actions: list[Action] = []
    for node_id in sorted(board.nodes):
        actions.extend((Action("comm", node_id, prompt_id=1), Action("shield", node_id)))
    actions.extend(_cmg_cut_candidates(board, cut_limit))
    return [action for action in actions if is_legal_action(action, board, budget)]


def choose_cmg_action(
    board: Blackboard, ledger: ResponseLedger, profile: CalibrationProfile, budget: float,
    *, cut_limit: int = 64, iterations: int = 200, threshold: float = 1e-8, planning_seconds: float = 1.0,
) -> ScoredCandidate | None:
    if not profile.verified:
        raise CMGPlanningError("profile_unavailable")
    started = time.monotonic()
    state = PredictiveState.from_blackboard(board)
    predictor = SettlementPredictor(profile, iterations=iterations, threshold=threshold)
    before = predictor.score(state)
    scored: list[ScoredCandidate] = []
    for action in enumerate_cmg_actions(board, budget, cut_limit):
        if time.monotonic() - started > planning_seconds:
            raise CMGPlanningError("planning_timeout")
        delta: float | None = None
        response_sigma = 0.0
        if action.kind == "comm":
            node = board.nodes[action.target_node_1]
            response = ledger.predicted_delta(action.target_node_1, node.persona, 1, profile)
            if response is None:
                raise CMGPlanningError("missing_response_prior")
            delta, response_sigma = response
        after = predictor.score(state.apply(action, delta))
        residual = profile.residual_for(action.kind)
        response_score_sigma = 0.0
        if action.kind == "comm" and response_sigma > 0.0:
            assert delta is not None
            # Priors are measured in w units.  Transform their uncertainty
            # through the same settlement score before combining it with the
            # score-space calibration residual (important for high-degree nodes).
            score_high = predictor.score(state.apply(action, delta + response_sigma))
            score_low = predictor.score(state.apply(action, delta - response_sigma))
            response_score_sigma = max(abs(score_high - after), abs(after - score_low))
        sigma = math.hypot(residual, response_score_sigma)
        gain = after - before
        roi = (gain - sigma) / action_cost(action)
        if not all(math.isfinite(value) for value in (after, sigma, gain, roi)):
            raise CMGPlanningError("nonfinite_prediction")
        candidate_id = (
            f"comm:{action.target_node_1}:1" if action.kind == "comm" else
            f"shield:{action.target_node_1}" if action.kind == "shield" else
            f"cut:{action.target_node_1}-{action.target_node_2}"
        )
        scored.append(ScoredCandidate(candidate_id, action, before, after, gain, sigma, roi, delta))
    positives = [item for item in scored if item.lcb_roi > 0.0]
    return min(positives, key=lambda item: (-item.lcb_roi, item.candidate_id)) if positives else None

# End inline: src/starnet/policy/cmg.py

# Begin inline: src/starnet/policy/structural.py
"""Fail-closed structural planning for B3 and B4.

The planner only operates on a copied :class:`PredictiveState`.  It never
calls the environment and never writes the Blackboard.  A plan is ordered as
``structure actions, then persuasion completion``; this makes it impossible
to count persuasion on a node that a later hypothetical shield removes.
"""


from collections.abc import Callable, Iterable
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

import networkx as nx



@dataclass(frozen=True)
class PlanCandidate:
    """A complete executable plan and its first public action."""

    candidate_id: str
    actions: tuple[Action, ...]
    first_action: Action | None
    cost: float
    steps: int
    predicted_final_score: float
    gain: float
    risk: float
    topology_summary: dict[str, Any]
    evidence_ids: tuple[str, ...] = ()
    structure_actions: tuple[Action, ...] = ()
    persuasion_actions: tuple[Action, ...] = ()

    @property
    def conservative_gain(self) -> float:
        return self.gain - self.risk

    @property
    def full_plan(self) -> tuple[Action, ...]:
        return self.actions

    @property
    def first_public_action(self) -> Action | None:
        return self.first_action

    @property
    def predicted_score(self) -> float:
        return self.predicted_final_score

    @property
    def valid(self) -> bool:
        return self.first_action is not None and self.cost >= 0 and self.steps == len(self.actions)


@dataclass(frozen=True)
class StructuralActionScore:
    action: Action
    score_before: float
    score_after: float
    gain: float
    risk: float
    category: str
    evidence_id: str


def _action_id(action: Action) -> str:
    if action.kind == "comm":
        return f"comm:{action.target_node_1}:{action.prompt_id}"
    if action.kind == "cut":
        return f"cut:{action.target_node_1}-{action.target_node_2}"
    return f"{action.kind}:{action.target_node_1}"


def _state_key(state: PredictiveState) -> tuple[object, ...]:
    return (
        tuple((node, state.nodes[node].w, state.nodes[node].persona, state.nodes[node].comm_left)
              for node in sorted(state.nodes)),
        tuple(sorted(state.edges)),
    )


class StructuralPlanner:
    """Deterministic B3 single-action and B4 depth-two beam planner."""

    def __init__(
        self,
        profile: CalibrationProfile,
        *,
        ledger: ResponseLedger | None = None,
        depth: int = 2,
        width: int = 4,
        candidate_limit: int = 12,
        enable_pair_cut_experiment: bool = False,
        pair_cut_edge_limit: int = 16,
        pair_cut_plan_limit: int = 6,
        predictor: SettlementPredictor | None = None,
        score_fn: Callable[[PredictiveState], float] | None = None,
    ) -> None:
        if depth <= 0 or width <= 0 or candidate_limit <= 0:
            raise ValueError("beam and candidate limits must be positive")
        if pair_cut_edge_limit < 2 or pair_cut_edge_limit > 16 or pair_cut_plan_limit <= 0:
            raise ValueError("invalid pair-cut experiment limits")
        self.profile = profile
        self.ledger = ledger or ResponseLedger()
        self.depth, self.width, self.candidate_limit = depth, width, candidate_limit
        # This is deliberately a constructor-only experiment flag.  No
        # runtime/default configuration enables it, so B1 and ordinary B4
        # keep their established candidate set and cost profile.
        self.enable_pair_cut_experiment = enable_pair_cut_experiment
        self.pair_cut_edge_limit = pair_cut_edge_limit
        self.pair_cut_plan_limit = pair_cut_plan_limit
        self.predictor = predictor or SettlementPredictor(profile)
        self._score_fn = score_fn
        self._score_cache: dict[tuple[object, ...], float] = {}

    @property
    def _cache_safe(self) -> bool:
        """Only cache small-model scores; graph-state keys are expensive.

        The verified component score is O(V+E), while a cache key serialises
        every node and edge.  Retaining hundreds of such keys costs far more
        memory than recomputing the closed-form score on 50/100-node graphs.
        """
        return self._score_fn is not None or self.profile.model != "component_degree_plus_one"

    @property
    def eligible(self) -> bool:
        return self.profile.structure_eligible

    def _score(self, state: PredictiveState) -> float:
        if self._score_fn is not None:
            value = float(self._score_fn(state))
            if not math.isfinite(value):
                raise ValueError("nonfinite score")
            return value
        params = (self.profile.model, self.profile.rho, self.profile.gamma,
                  self.profile.a, self.profile.b, self.predictor.iterations,
                  self.predictor.threshold)
        key = params + _state_key(state)
        if not self._cache_safe:
            return float(self.predictor.score(state))
        if key not in self._score_cache:
            # Bound hypothetical-state retention for unverified/legacy models.
            # Eviction changes neither a score nor candidate ordering.
            if len(self._score_cache) >= 256:
                self._score_cache.clear()
            self._score_cache[key] = float(self.predictor.score(state))
        return self._score_cache[key]

    def influence_coefficients(self, state: PredictiveState, delta: float = 1.0) -> dict[int, float]:
        """Recompute score sensitivities for this exact topology."""
        if delta <= 0 or not math.isfinite(delta):
            raise ValueError("delta must be positive and finite")
        base = self._score(state)
        result: dict[int, float] = {}
        for node_id in sorted(state.nodes):
            changed = PredictiveState(
                nodes={node: type(value)(value.w, value.persona, value.comm_left)
                       for node, value in state.nodes.items()},
                edges=set(state.edges), dead_nodes=set(state.dead_nodes),
            )
            changed.nodes[node_id].w += delta
            result[node_id] = (self._score(changed) - base) / delta
        return result

    def _structure_scores(self, state: PredictiveState, budget: float) -> list[StructuralActionScore]:
        board = state.to_blackboard()
        before = self._score(state)
        scores: list[StructuralActionScore] = []
        # Full scans by action class are intentional: candidate coverage must
        # not be replaced by a negative-node/bridge heuristic.
        actions = [Action("shield", node_id) for node_id in sorted(state.nodes)]
        actions += [Action("cut", left, target_node_2=right) for left, right in sorted(state.edges)]
        residuals = self.profile.structure_action_residual_std or self.profile.settlement_residual_std
        for action in actions:
            if not is_legal_action(action, board, budget):
                continue
            after_state = state.apply(action)
            after = self._score(after_state)
            residual = float(residuals.get(action.kind, math.inf))
            if not math.isfinite(residual):
                continue
            category = "shield" if action.kind == "shield" else "cut"
            scores.append(StructuralActionScore(
                action, before, after, after - before, max(0.0, residual), category,
                f"structure:{_action_id(action)}",
            ))
        return scores

    def structure_candidates(self, board: Blackboard, budget: float) -> tuple[StructuralActionScore, ...]:
        """Cheap full scan + class-balanced finite scoring layer."""
        if not self.eligible:
            return ()
        raw = self._structure_scores(PredictiveState.from_blackboard(board), budget)
        selected: list[StructuralActionScore] = []
        for category in ("shield", "cut"):
            category_items = sorted(
                (item for item in raw if item.category == category),
                key=lambda item: (-item.gain, item.action.kind, _action_id(item.action)),
            )
            selected.extend(category_items[:4])
        selected_ids = {_action_id(item.action) for item in selected}
        remainder = sorted(
            (item for item in raw if _action_id(item.action) not in selected_ids),
            key=lambda item: (-item.gain, item.action.kind, _action_id(item.action)),
        )
        selected.extend(remainder[:max(0, self.candidate_limit - len(selected))])
        return tuple(selected[: self.candidate_limit])

    # Names kept deliberately small for experiment drivers and notebooks.
    score_actions = structure_candidates

    def _pair_cut_sequences(
        self, initial: PredictiveState, budget: float,
    ) -> tuple[tuple[Action, Action], ...]:
        """Return bounded legal cut pairs ranked by their joint topology gain.

        Pair scoring is exact for the configured settlement model.  It is an
        opt-in experiment for interactions which a singleton screen cannot
        observe (for example, two cuts needed to isolate a harmful cluster).
        At most 16 edges and C(16, 2)=120 pair states are evaluated.
        """
        scored_edges = [
            item for item in self._structure_scores(initial, budget)
            if item.action.kind == "cut"
        ]
        # Give endpoints with publicly negative opinion a deterministic
        # priority, then retain the existing calibrated singleton order.  The
        # later joint score, rather than this screen, decides which pairs run.
        def edge_key(item: StructuralActionScore) -> tuple[float, float, str]:
            left = initial.nodes[item.action.target_node_1]
            assert item.action.target_node_2 is not None
            right = initial.nodes[item.action.target_node_2]
            negative_mass = max(0.0, -left.w) + max(0.0, -right.w)
            return (-negative_mass, -item.gain, _action_id(item.action))

        edges = sorted(scored_edges, key=edge_key)[: self.pair_cut_edge_limit]
        baseline = self._score(initial)
        pairs: list[tuple[float, str, tuple[Action, Action]]] = []
        for first_index, first_item in enumerate(edges):
            first = first_item.action
            first_state = initial.apply(first)
            first_board = first_state.to_blackboard()
            first_budget = budget - action_cost(first)
            for second_item in edges[first_index + 1:]:
                # This experiment is specifically for complementarities that
                # a greedy singleton screen rejects.  Ordinary profitable
                # cuts remain the responsibility of the regular beam.
                if first_item.gain > 0.0 or second_item.gain > 0.0:
                    continue
                second = second_item.action
                # The second action is checked against the state after the
                # first cut.  This prevents stale-edge attempts, which spend
                # budget in the environment even when they return None.
                if not is_legal_action(second, first_board, first_budget):
                    continue
                joint_gain = self._score(first_state.apply(second)) - baseline
                if math.isfinite(joint_gain):
                    sequence = (first, second)
                    pairs.append((joint_gain, "|".join(_action_id(a) for a in sequence), sequence))
        pairs.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[2] for item in pairs[: self.pair_cut_plan_limit])

    def _response_delta(self, state: PredictiveState, action: Action) -> float | None:
        node = state.nodes.get(action.target_node_1)
        if node is None or action.prompt_id is None:
            return None
        turn = 4 - int(node.comm_left or 0)
        if turn not in (1, 2, 3):
            return None
        response = self.ledger.predicted_delta(
            action.target_node_1, node.persona, action.prompt_id, self.profile, turn=turn
        )
        return None if response is None else max(0.0, float(response[0]))

    def _complete_persuasion(
        self, state: PredictiveState, budget: float, remaining_steps: int,
    ) -> tuple[PredictiveState, tuple[Action, ...], float]:
        """Fill residual resources greedily after all structure actions."""
        actions: list[Action] = []
        current = state
        left_budget, left_steps = budget, remaining_steps
        linear_influence: dict[int, float] | None = None
        if self.profile.model == "component_degree_plus_one":
            # For a fixed topology the verified component score is linear in
            # every w_i.  Compute its exact coefficient once; repeated
            # persuasion hypotheses then need no graph copy or connectivity
            # recomputation.  Structure actions still create fresh topologies
            # and therefore recompute this map per terminal candidate.
            linear_influence = self.influence_coefficients(current)
        while left_budget >= 2.0 and left_steps > 0:
            board = current.to_blackboard()
            if linear_influence is not None:
                options_linear: list[tuple[float, str, Action, float]] = []
                for node_id in sorted(current.nodes):
                    action = Action("comm", node_id, prompt_id=1)
                    if not is_legal_action(action, board, left_budget):
                        continue
                    delta = self._response_delta(current, action)
                    if delta is None:
                        continue
                    gain = linear_influence.get(node_id, 0.0) * delta
                    if math.isfinite(gain) and gain > 0:
                        options_linear.append((gain, _action_id(action), action, delta))
                if not options_linear:
                    break
                _, _, action, delta = max(options_linear, key=lambda item: (item[0], "".join(reversed(item[1]))))
                current = current.apply(action, delta)
            else:
                options: list[tuple[float, str, Action, PredictiveState]] = []
                current_score = self._score(current)
                for node_id in sorted(current.nodes):
                    action = Action("comm", node_id, prompt_id=1)
                    if not is_legal_action(action, board, left_budget):
                        continue
                    delta = self._response_delta(current, action)
                    if delta is None:
                        continue
                    after_state = current.apply(action, delta)
                    gain = self._score(after_state) - current_score
                    if math.isfinite(gain) and gain > 0:
                        options.append((gain, _action_id(action), action, after_state))
                if not options:
                    break
                _, _, action, current = max(options, key=lambda item: (item[0], "".join(reversed(item[1]))))
            actions.append(action)
            left_budget -= action_cost(action)
            left_steps -= 1
        return current, tuple(actions), budget - left_budget

    def _make_plan(
        self, initial: PredictiveState, structure: tuple[Action, ...],
        budget: float, remaining_steps: int, baseline_score: float,
    ) -> PlanCandidate | None:
        state = initial
        left_budget, left_steps = budget, remaining_steps
        for action in structure:
            board = state.to_blackboard()
            if left_steps <= 0 or not is_legal_action(action, board, left_budget):
                return None
            state = state.apply(action)
            left_budget -= action_cost(action)
            left_steps -= 1
        structure_state = state
        state, persuasion, _persuasion_cost = self._complete_persuasion(state, left_budget, left_steps)
        actions = structure + persuasion
        if not actions:
            return PlanCandidate("complete", (), None, 0.0, 0, baseline_score, 0.0, 0.0,
                                 self._topology_summary(initial), (), (), ())
        cost = sum(action_cost(action) for action in actions)
        residuals = self.profile.structure_action_residual_std or self.profile.settlement_residual_std
        risk_sq = sum(float(residuals.get(action.kind, 0.0)) ** 2 for action in structure)
        # Response priors are expressed in opinion units while the plan gain
        # is terminal-score units.  Reproduce each hypothetical communication
        # from its pre-action state and transform ± one standard deviation
        # through the same settlement predictor before combining uncertainty.
        risk_state = structure_state
        comm_residual = float(residuals.get("comm", self.profile.residual_for("comm")))
        for action in persuasion:
            node = risk_state.nodes.get(action.target_node_1)
            if node is None or action.prompt_id is None or node.comm_left is None:
                return None
            turn = 4 - node.comm_left
            response = self.ledger.predicted_delta(
                action.target_node_1, node.persona, action.prompt_id, self.profile, turn=turn
            )
            if response is None:
                return None
            delta, response_std = max(0.0, float(response[0])), max(0.0, float(response[1]))
            mean_state = risk_state.apply(action, delta)
            mean_score = self._score(mean_state)
            if response_std > 0.0:
                high_score = self._score(risk_state.apply(action, delta + response_std))
                low_score = self._score(risk_state.apply(action, delta - response_std))
                response_score_std = max(abs(high_score - mean_score), abs(mean_score - low_score))
            else:
                response_score_std = 0.0
            if not math.isfinite(comm_residual) or not math.isfinite(response_score_std):
                return None
            risk_sq += math.hypot(comm_residual, response_score_std) ** 2
            risk_state = mean_state
        final_score = self._score(state)
        gain = final_score - baseline_score
        identifier = "plan:" + "|".join(_action_id(action) for action in actions)
        return PlanCandidate(
            identifier, actions, actions[0], cost, len(actions), final_score, gain,
            math.sqrt(max(0.0, risk_sq)), self._topology_summary(state),
            tuple(f"plan:{_action_id(action)}" for action in actions),
            structure, persuasion,
        )

    @staticmethod
    def _topology_summary(state: PredictiveState) -> dict[str, Any]:
        graph = nx.Graph()
        graph.add_nodes_from(state.nodes)
        graph.add_edges_from(state.edges)
        return {
            "nodes": len(state.nodes),
            "edges": len(state.edges),
            "components": 0 if not state.nodes else nx.number_connected_components(graph),
            "shielded": sorted(state.dead_nodes),
        }

    def plan_candidates(
        self, board: Blackboard, budget: float, remaining_steps: int,
        mode: PolicyMode = PolicyMode.B4_BEAM_STRUCTURE,
    ) -> tuple[PlanCandidate, ...]:
        if not self.eligible:
            return ()
        initial = PredictiveState.from_blackboard(board)
        baseline_score = self._score(initial)
        baseline = self._make_plan(initial, (), budget, remaining_steps, baseline_score)
        if baseline is None:
            return ()
        if mode is PolicyMode.B3_SINGLE_STRUCTURE:
            # Score every legal structure action for coverage, but retain only
            # the same bounded set that can later become runnable candidates.
            # Keeping every full persuasion completion is the dominant memory
            # cost on 100-node dense graphs.
            plans: list[PlanCandidate] = [baseline]
            for item in self.structure_candidates(board, budget):
                plan = self._make_plan(initial, (item.action,), budget, remaining_steps, baseline_score)
                if plan is not None and plan.conservative_gain > 0:
                    plans.append(plan)
                    plans = sorted(plans, key=lambda item: (-item.conservative_gain, item.candidate_id))[: self.candidate_limit + 1]
            return tuple(sorted(plans, key=lambda item: (-item.conservative_gain, item.candidate_id)))

        # Beam state keeps structural actions only.  Every terminal state is
        # independently completed with persuasion and can stop immediately.
        pool = list(self.structure_candidates(board, budget))
        beam: list[tuple[PredictiveState, tuple[Action, ...]]] = [(initial, ())]
        terminals: list[PlanCandidate] = [baseline]
        if self.enable_pair_cut_experiment and self.depth >= 2 and remaining_steps >= 2:
            # Evaluate this small set before the beam.  A normal beam ranks
            # partial paths by singleton value and can prune an intentionally
            # loss-making first cut even when its two-cut terminal is useful.
            for sequence in self._pair_cut_sequences(initial, budget):
                plan = self._make_plan(initial, sequence, budget, remaining_steps, baseline_score)
                if plan is not None and plan.conservative_gain > 0.0:
                    terminals.append(plan)
        for _depth in range(min(self.depth, remaining_steps)):
            expanded: list[tuple[float, str, PredictiveState, tuple[Action, ...]]] = []
            for state, sequence in beam:
                available = sorted(
                    self._structure_scores(state, budget - sum(action_cost(a) for a in sequence)),
                    key=lambda item: (-item.gain, _action_id(item.action)),
                )
                # The root keeps the bounded candidate pool (which is class
                # balanced); later beam layers need only the top width local
                # expansions.  Evaluating a complete persuasion tail for all
                # hundreds of edges is not a beam search and dominates both
                # runtime and allocator churn on 100-node graphs.
                limit = self.candidate_limit if not sequence else self.width
                available = available[:limit]
                for item in available:
                    if item.action in sequence:
                        continue
                    next_sequence = sequence + (item.action,)
                    plan = self._make_plan(initial, next_sequence, budget, remaining_steps, baseline_score)
                    if plan is not None:
                        terminals.append(plan)
                        expanded.append((plan.conservative_gain, plan.candidate_id,
                                         state.apply(item.action), next_sequence))
            # Only the top beam can be expanded and only the top runnable
            # plans can reach the controller; discard the rest immediately.
            terminals = sorted(
                terminals, key=lambda item: (-item.conservative_gain, item.candidate_id)
            )[: self.candidate_limit + 1]
            unique: dict[tuple[object, ...], tuple[float, str, PredictiveState, tuple[Action, ...]]] = {}
            for item in sorted(expanded, key=lambda value: (-value[0], value[1])):
                unique.setdefault(_state_key(item[2]), item)
            beam = [(item[2], item[3]) for item in list(unique.values())[: self.width]]
            if not beam:
                break
        accepted = [item for item in terminals if item.conservative_gain > 0 or not item.structure_actions]
        # Deduplicate plans and make the stable ordering explicit.
        dedup = {item.candidate_id: item for item in accepted}
        return tuple(sorted(dedup.values(), key=lambda item: (-item.conservative_gain, item.candidate_id))[: self.candidate_limit + 1])

    def plan(
        self, board: Blackboard, budget: float, remaining_steps: int,
        mode: PolicyMode = PolicyMode.B4_BEAM_STRUCTURE,
    ) -> PlanCandidate | None:
        """Return the best complete plan, or ``None`` when the gate is closed."""
        plans = self.plan_candidates(board, budget, remaining_steps, mode)
        return plans[0] if plans else None


def _public_adjacency(board: Blackboard) -> dict[int, set[int]]:
    """Build an adjacency view from the already scanned public graph."""
    adjacency = {node_id: set() for node_id in board.nodes}
    for left, right in board.edges:
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    return adjacency


def _public_structure_risk_features(board: Blackboard) -> tuple[float, float, float]:
    """Return public-only peace share, positive mass and violent negative mass.

    The masses use the same public ``degree + 1`` factor as the qualified
    settlement relation.  They are screening features, not hidden-state
    predictions: the response coefficient ``r`` is never consulted.
    """
    adjacency = _public_adjacency(board)
    node_count = len(board.nodes)
    if node_count == 0:
        return 0.0, 0.0, 0.0
    peace_share = sum(
        node.persona == "和平" or node.w >= 0.0 for node in board.nodes.values()
    ) / node_count
    positive_mass = sum(
        (len(adjacency[node_id]) + 1) * max(0.0, node.w)
        for node_id, node in board.nodes.items()
    )
    violent_negative_mass = sum(
        (len(adjacency[node_id]) + 1) * max(0.0, -node.w)
        for node_id, node in board.nodes.items()
        if node.persona == "暴力"
    )
    return peace_share, positive_mass, violent_negative_mass


def public_positive_graph_gate_closed(board: Blackboard) -> bool:
    """Return whether public evidence says topology is overwhelmingly positive."""
    peace_share, positive_mass, violent_negative_mass = _public_structure_risk_features(board)
    return (
        peace_share >= 0.85
        and positive_mass >= 2.0 * max(1.0, violent_negative_mass)
    )


def _public_negative_nonpeace(node: Any) -> bool:
    """Recognize a publicly negative node without treating neutral as peace."""
    return node.w < 0.0 and node.persona != "和平"


def _component_influence_coefficients(board: Blackboard) -> dict[int, float]:
    """Return the closed-form communication coefficients for this board."""
    adjacency = _public_adjacency(board)
    unseen = set(adjacency)
    coefficients: dict[int, float] = {}
    while unseen:
        start = min(unseen)
        component: list[int] = []
        stack = [start]
        unseen.remove(start)
        while stack:
            node_id = stack.pop()
            component.append(node_id)
            for neighbor in adjacency[node_id]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        denominator = sum(len(adjacency[node_id]) + 1 for node_id in component)
        factor = len(component) / denominator
        coefficients.update(
            {node_id: factor * (len(adjacency[node_id]) + 1) for node_id in component}
        )
    return coefficients


def public_structure_risk_allowed(
    board: Blackboard, action: Action, predicted_gain: float,
) -> bool:
    """Conservatively screen structure actions using public facts only.

    A high-positive, peace-majority graph is treated as a fragile positive
    propagation network: spending budget on topology changes is disabled even
    if a point estimate gives a small positive gain.  Outside that gate, the
    allowed action families are deliberately narrow and semantically tied to
    the observed risk direction.  This avoids selecting a favorable-looking
    shield/cut merely because it beats an uncertain response prior.
    """
    if not math.isfinite(predicted_gain) or predicted_gain <= 0.0:
        return False
    # ``peace_share`` includes publicly non-negative nodes.  The strict 0.85
    # threshold is intentionally reserved for an overwhelmingly positive
    # graph, so a mixed ER graph is not accidentally treated as WS-like.  A
    # second mass check prevents a genuinely large violent-negative cluster
    # from being hidden by the persona majority alone.
    if public_positive_graph_gate_closed(board):
        return False
    return _public_structure_direction_allowed(board, action)


def _public_structure_direction_allowed(board: Blackboard, action: Action) -> bool:
    """Check target signs after the episode's public graph gate is known."""
    if action.kind == "shield":
        node = board.nodes.get(action.target_node_1)
        return node is not None and _public_negative_nonpeace(node)
    if action.kind == "cut" and action.target_node_2 is not None:
        left = board.nodes.get(action.target_node_1)
        right = board.nodes.get(action.target_node_2)
        if left is None or right is None:
            return False
        return (
            _public_negative_nonpeace(left)
            and not _public_negative_nonpeace(right)
        ) or (
            _public_negative_nonpeace(right)
            and not _public_negative_nonpeace(left)
        )
    return False


class ExperimentalPublicGreedyPlanner:
    """One-step public-state action scorer for an explicit experiment.

    Unlike B3/B4 this planner does not consume a frozen runtime calibration
    profile.  It is therefore intentionally *not* wired into the default
    submission.  It uses only the topology and opinions already returned by
    public scans, plus a caller-supplied response prior for communication.
    Every action is rescored after execution, and only a strictly positive
    terminal-score gain is exposed.
    """

    def __init__(
        self,
        response_fn: Callable[[int, Any, int], float],
        *,
        candidate_limit: int = 24,
        conservative_structure: bool = True,
        min_observed_responses: int = 4,
        structure_roi_margin: float = 1.25,
        defer_comm_if_shieldable: bool = False,
    ) -> None:
        if (
            candidate_limit <= 0
            or min_observed_responses < 0
            or not math.isfinite(structure_roi_margin)
            or structure_roi_margin < 1.0
            or not isinstance(defer_comm_if_shieldable, bool)
        ):
            raise ValueError("invalid public-greedy candidate or risk limits")
        self.response_fn = response_fn
        self.candidate_limit = candidate_limit
        self.conservative_structure = conservative_structure
        self.min_observed_responses = min_observed_responses
        self.structure_roi_margin = structure_roi_margin
        self.defer_comm_if_shieldable = defer_comm_if_shieldable
        self.predictor = SettlementPredictor(
            CalibrationProfile(gate_passed=False, model="component_degree_plus_one")
        )

    @staticmethod
    def _candidate_id(action: Action, turn: int | None = None) -> str:
        if action.kind == "comm":
            assert turn in (1, 2, 3)
            return f"comm:{action.target_node_1}:{turn}"
        if action.kind == "cut":
            return f"cut:{action.target_node_1}-{action.target_node_2}"
        return f"shield:{action.target_node_1}"

    def candidates(
        self,
        board: Blackboard,
        budget: float,
        failed_actions: Iterable[object] = (),
        observed_response_count: int = 0,
    ) -> list[Candidate]:
        state = PredictiveState.from_blackboard(board)
        prepare = getattr(self.predictor, "prepare", None)
        prepared = prepare(state) if prepare is not None else None
        baseline = prepared.score() if prepared is not None else self.predictor.score(state)
        structure_enabled = not self.conservative_structure or (
            observed_response_count >= self.min_observed_responses
            and not public_positive_graph_gate_closed(board)
        )
        public_influence = _component_influence_coefficients(board)
        comm_rois: dict[int, float] = {}
        for node_id, node in sorted(board.nodes.items()):
            if node.comm_left is None or node.comm_left <= 0:
                continue
            turn = 4 - node.comm_left
            if turn not in (1, 2, 3):
                continue
            action = Action("comm", node_id, prompt_id=1)
            if not is_legal_action(action, board, budget):
                continue
            response = self.response_fn(node_id, node, turn)
            if math.isfinite(float(response)):
                comm_rois[node_id] = public_influence.get(node_id, 0.0) * max(
                    0.0, float(response)
                ) / action_cost(action)
        failed = set(failed_actions)
        hypotheses: list[tuple[Action, float | None, int | None]] = []
        for node_id, node in sorted(board.nodes.items()):
            if node.comm_left is not None and node.comm_left > 0:
                turn = 4 - node.comm_left
                if turn in (1, 2, 3):
                    hypotheses.append(
                        (Action("comm", node_id, prompt_id=1), self.response_fn(node_id, node, turn), turn)
                    )
            hypotheses.append((Action("shield", node_id), None, None))
        hypotheses.extend(
            (Action("cut", left, target_node_2=right), None, None)
            for left, right in sorted(state.edges)
        )

        result: list[Candidate] = []
        for action, delta, turn in hypotheses:
            candidate_id = self._candidate_id(action, turn)
            if candidate_id in failed or action in failed:
                continue
            if not is_legal_action(action, board, budget):
                continue
            if action.kind in {"cut", "shield"} and (
                not structure_enabled
                or (self.conservative_structure and not _public_structure_direction_allowed(board, action))
            ):
                continue
            # Keep communication scores bit-for-bit on the same closed-form
            # path as B1.  The predictor difference is mathematically equal,
            # but tiny operation-order differences can otherwise reorder tied
            # targets when the structure gate is closed.
            gain = (
                public_influence.get(action.target_node_1, 0.0) * float(delta)
                if action.kind == "comm"
                else (prepared.score_after(action) if prepared is not None
                      else self.predictor.score(state.apply(action, delta))) - baseline
            )
            if not math.isfinite(gain) or gain <= 0.0:
                continue
            if (
                self.conservative_structure
                and action.kind in {"cut", "shield"}
            ):
                # A shield and a communication on its target are mutually
                # exclusive alternatives.  Do not let that soon-to-be-
                # removed target's ROI hide a deterministic shield gain;
                # cutting leaves both endpoints alive, so its comparison
                # keeps the full communication set.
                excluded = {action.target_node_1} if action.kind == "shield" else set()
                alternative_comm_roi = max(
                    (roi for node_id, roi in comm_rois.items() if node_id not in excluded),
                    default=0.0,
                )
                if (
                    alternative_comm_roi > 0.0
                    and gain / action_cost(action)
                    < self.structure_roi_margin * alternative_comm_roi
                ):
                    continue
            result.append(
                Candidate(
                    candidate_id=candidate_id,
                    action=action,
                    priority=0,
                    score=gain,
                    roi=gain / action_cost(action),
                    reason=f"public terminal gain {gain:.6f}",
                    evidence_ids=(f"public-score:{candidate_id}",),
                )
            )
        if self.defer_comm_if_shieldable:
            shieldable_targets = {
                candidate.action.target_node_1
                for candidate in result
                if candidate.action.kind == "shield" and candidate.score > 0.0
            }
            result = [
                candidate for candidate in result
                if not (
                    candidate.action.kind == "comm"
                    and candidate.action.target_node_1 in shieldable_targets
                )
            ]
        return sorted(
            result,
            key=lambda item: (-round(item.roi, 10), -round(item.score, 10), item.candidate_id),
        )[: self.candidate_limit]


__all__ = [
    "ExperimentalPublicGreedyPlanner",
    "PlanCandidate",
    "StructuralActionScore",
    "StructuralPlanner",
]

# End inline: src/starnet/policy/structural.py

# Begin inline: src/starnet/policy/budget_experiment.py
"""Offline-only budget-complete structural search on copied public state."""


from dataclasses import dataclass
import heapq
import math
from typing import Any, Callable

import networkx as nx


ResponseFn = Callable[[int, Any, int], float]


@dataclass(frozen=True)
class BudgetPlan:
    score: float
    actions: tuple[Action, ...]


def _connected_structure_score(
    state: PredictiveState, action: Action, graph: nx.Graph,
    responses: dict[tuple[int, int], float], budget: float, steps: int,
) -> float:
    """Fast linear score when a certified non-bridge/non-articulation changes."""
    removed = action.target_node_1 if action.kind == "shield" else None
    affected = set(graph[removed]) if removed is not None else {action.target_node_1, action.target_node_2}
    degrees = {node_id: graph.degree[node_id] + 1 - int(node_id in affected)
               for node_id in state.nodes if node_id != removed}
    if not degrees:
        return 0.0
    factor = len(degrees) / sum(degrees.values())
    score = sum(factor * degree * state.nodes[node_id].w for node_id, degree in degrees.items())
    gains = [factor * degree * responses[node_id, turn]
             for node_id, degree in degrees.items() if state.nodes[node_id].comm_left
             for turn in range(4 - state.nodes[node_id].comm_left, 4)]
    for gain in heapq.nlargest(min(int(budget // 2), steps), gains):
        if gain > 0:
            score += gain
    return score


def communication_tail(
    state: PredictiveState, budget: float, response_fn: ResponseFn, remaining_steps: int,
    *, include_actions: bool = True,
) -> BudgetPlan:
    """Exact equal-cost allocation for nonnegative diminishing responses.

    Under the experimental degree-plus-one consensus model, a fixed
    topology's score is linear. A heap preserves each node's slot precedence.
    """
    adjacency = {node_id: set() for node_id in state.nodes}
    for left, right in state.edges:
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    coefficients: dict[int, float] = {}
    unseen = set(state.nodes)
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        component = [start]
        for node_id in component:
            for neighbor in sorted(adjacency[node_id]):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.append(neighbor)
        factor = len(component) / sum(len(adjacency[node_id]) + 1 for node_id in component)
        coefficients.update({node_id: factor * (len(adjacency[node_id]) + 1) for node_id in component})
    score = sum(coefficients[node_id] * node.w for node_id, node in state.nodes.items())
    heap: list[tuple[float, str, int, int]] = []
    gains: dict[tuple[int, int], float] = {}
    for node_id, node in sorted(state.nodes.items()):
        if not node.comm_left:
            continue
        previous = math.inf
        for turn in range(4 - node.comm_left, 4):
            delta = float(response_fn(node_id, node, turn))
            if not math.isfinite(delta) or delta < 0 or delta > previous + 1e-9:
                raise ValueError("response must be finite, nonnegative and diminishing")
            previous = delta
            gains[node_id, turn] = coefficients[node_id] * delta
        turn = 4 - node.comm_left
        heapq.heappush(heap, (-gains[node_id, turn], f"comm:{node_id}:{turn}", node_id, turn))
    slots = min(max(0, int(budget // 2)), max(0, remaining_steps))
    if not include_actions:
        for gain in heapq.nlargest(slots, gains.values()):
            if gain > 0:
                score += gain
        return BudgetPlan(score, ())
    actions: list[Action] = []
    for _ in range(slots):
        if not heap or heap[0][0] >= 0:
            break
        negative_gain, _, node_id, turn = heapq.heappop(heap)
        score -= negative_gain
        actions.append(Action("comm", node_id, prompt_id=1))
        if turn < 3:
            heapq.heappush(heap, (-gains[node_id, turn + 1], f"comm:{node_id}:{turn + 1}", node_id, turn + 1))
    return BudgetPlan(score, tuple(actions))


def budget_plan(
    board: Blackboard, budget: float, response_fn: ResponseFn, *,
    remaining_steps: int, depth: int = 2, width: int = 4,
) -> BudgetPlan:
    """Compare complete allocations, retaining the public structure gate.

    This module has no production configuration flag. Calibration and scenario
    promotion are required before a runtime may expose its plans to an LLM.
    """
    if depth < 0 or width <= 0 or remaining_steps < 0 or not math.isfinite(budget) or budget < 0:
        raise ValueError("invalid planning limits")
    initial = PredictiveState.from_blackboard(board)
    # Structure changes neither a survivor's opinion nor its response slots.
    responses = {(node_id, turn): response_fn(node_id, node, turn)
                 for node_id, node in initial.nodes.items() if node.comm_left
                 for turn in range(4 - node.comm_left, 4)}
    fixed_response = lambda node_id, _node, turn: responses[node_id, turn]
    best = communication_tail(initial, budget, fixed_response, remaining_steps)
    hypotheses = [Action("shield", node_id) for node_id in sorted(initial.nodes)]
    hypotheses += [Action("cut", left, target_node_2=right) for left, right in sorted(initial.edges)]
    # The gate sees only returned facts, never a Blackboard with predictions.
    hypotheses = [action for action in hypotheses if is_legal_action(action, board, budget)
                  and public_structure_risk_allowed(board, action, 1.0)]
    beam = [(initial, (), budget)]
    for _ in range(min(depth, remaining_steps)):
        ranked = []
        visited = set()
        for state, prefix, available in beam:
            graph = nx.Graph()
            graph.add_nodes_from(state.nodes)
            graph.add_edges_from(state.edges)
            connected = bool(state.nodes) and nx.is_connected(graph)
            articulations = set(nx.articulation_points(graph)) if connected else set()
            bridges = {tuple(sorted(edge)) for edge in nx.bridges(graph)} if connected else set()
            for action in hypotheses:
                cost = action_cost(action)
                if cost > available or action.target_node_1 not in state.nodes:
                    continue
                if action.kind == "cut" and tuple(sorted((action.target_node_1, action.target_node_2))) not in state.edges:
                    continue
                # Canonical topology changes also collapse cuts subsequently
                # erased by a shield, just like a full copied-state key.
                sequence = prefix + (action,)
                removed = frozenset(item.target_node_1 for item in sequence if item.kind == "shield")
                cuts = frozenset(tuple(sorted((item.target_node_1, item.target_node_2)))
                                 for item in sequence if item.kind == "cut"
                                 and item.target_node_1 not in removed and item.target_node_2 not in removed)
                key = (removed, cuts)
                # Equal topology with different costs must remain distinct.
                visit_key = (key, available - cost)
                if visit_key in visited:
                    continue
                visited.add(visit_key)
                fast = connected and (
                    action.kind == "shield" and action.target_node_1 not in articulations
                    or action.kind == "cut" and tuple(sorted((action.target_node_1, action.target_node_2))) not in bridges
                )
                changed = None
                if fast:
                    score = _connected_structure_score(state, action, graph, responses, available - cost, remaining_steps - len(sequence))
                else:
                    changed = state.apply(action)
                    score = communication_tail(changed, available - cost, fixed_response, remaining_steps - len(sequence), include_actions=False).score
                if score > best.score + 1e-9:
                    changed = changed or state.apply(action)
                    selected = communication_tail(changed, available - cost, fixed_response, remaining_steps - len(sequence))
                    best = BudgetPlan(selected.score, sequence + selected.actions)
                ranked.append((score, len(ranked), state, sequence, available - cost))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        beam = [(row[2].apply(row[3][-1]), row[3], row[4]) for row in ranked[:width]]
        if not beam:
            break
    return best

# End inline: src/starnet/policy/budget_experiment.py

# Begin inline: src/starnet/policy/fast_settlement_experiment.py
"""Experiment-only topology cache for exact component settlement scores."""


from collections import OrderedDict
from dataclasses import dataclass



# The official evaluator runs Python 3.9, where typing.TypeAlias is absent.
# A plain alias has identical runtime behavior and needs no backport.
TopologyKey = tuple[tuple[int, ...], frozenset[tuple[int, int]]]


@dataclass(frozen=True)
class _Component:
    nodes: tuple[int, ...]
    factors: tuple[int, ...]
    denominator: int

    @property
    def size(self) -> int:
        return len(self.nodes)


class FastComponentSettlement:
    """Cache topology terms while recomputing every opinion contribution."""

    def __init__(self, max_topologies: int = 128) -> None:
        if isinstance(max_topologies, bool) or max_topologies <= 0:
            raise ValueError("max_topologies must be positive")
        self.max_topologies = max_topologies
        self._cache: OrderedDict[TopologyKey, tuple[_Component, ...]] = OrderedDict()
        # Cache only topology coefficients, never opinions or live boards.
        # A small parent-graph cap bounds the additional action-coefficient table.
        self._action_cache: OrderedDict[TopologyKey, dict[Action, tuple[_Component, ...]]] = OrderedDict()
        self.max_action_topologies = 16
        self.hits = 0
        self.misses = 0

    @staticmethod
    def topology_key(state: PredictiveState) -> TopologyKey:
        nodes = tuple(sorted(state.nodes))
        node_set = set(nodes)
        edges = frozenset(
            (left, right)
            for left, right in state.edges
            if left in node_set and right in node_set
        )
        return nodes, edges

    @staticmethod
    def _compile(key: TopologyKey) -> tuple[_Component, ...]:
        nodes, edges = key
        parent = {node: node for node in nodes}
        degree = {node: 0 for node in nodes}

        def find(node: int) -> int:
            root = node
            while parent[root] != root:
                root = parent[root]
            while parent[node] != node:
                next_node = parent[node]
                parent[node] = root
                node = next_node
            return root

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for left, right in edges:
            degree[left] += 1
            degree[right] += 1
            union(left, right)
        groups: dict[int, list[int]] = {}
        for node in nodes:
            groups.setdefault(find(node), []).append(node)
        ordered = sorted((tuple(group) for group in groups.values()), key=lambda group: group[0])
        return tuple(
            _Component(
                component,
                tuple(degree[node] + 1 for node in component),
                sum(degree[node] + 1 for node in component),
            )
            for component in ordered
        )

    def _components(self, key: TopologyKey) -> tuple[_Component, ...]:
        components = self._cache.get(key)
        if components is None:
            self.misses += 1
            components = self._compile(key)
            self._cache[key] = components
            if len(self._cache) > self.max_topologies:
                self._cache.popitem(last=False)
        else:
            self.hits += 1
            self._cache.move_to_end(key)

        return components

    @staticmethod
    def _weighted_score(components, nodes) -> float:
        def component_score(component: _Component) -> float:
            weighted = 0.0
            for node, factor in zip(component.nodes, component.factors):
                weighted += factor * float(nodes[node].w)
            return component.size * weighted / component.denominator

        return sum(component_score(component) for component in components)

    def score(self, state: PredictiveState) -> float:
        if not state.nodes:
            return 0.0
        return self._weighted_score(self._components(self.topology_key(state)), state.nodes)

    def prepare(self, state: PredictiveState):
        """Reuse one topology key for a complete candidate-generation call."""
        key = self.topology_key(state)
        components = self._components(key)
        table = self._action_cache.get(key)
        if table is None:
            table = {}
            self._action_cache[key] = table
            if len(self._action_cache) > self.max_action_topologies:
                self._action_cache.popitem(last=False)
        else:
            self._action_cache.move_to_end(key)
        return _PreparedSettlement(self, state.nodes, key, components, table)

    @property
    def cache_size(self) -> int:
        return len(self._cache)


class _PreparedSettlement:
    """Ephemeral opinion view; only topology-derived tables enter the cache."""

    def __init__(self, predictor, nodes, key, components, table):
        self.predictor = predictor
        self.nodes = nodes
        self.key = key
        self.components = components
        self.table = table

    def score(self):
        return self.predictor._weighted_score(self.components, self.nodes)

    def score_after(self, action: Action):
        if action not in self.table:
            nodes, edges = self.key
            if action.kind == "shield" and action.target_node_1 in self.nodes:
                changed_nodes = tuple(node for node in nodes if node != action.target_node_1)
                changed_edges = frozenset(edge for edge in edges if action.target_node_1 not in edge)
            elif action.kind == "cut" and action.target_node_2 is not None:
                edge = tuple(sorted((action.target_node_1, action.target_node_2)))
                changed_nodes, changed_edges = nodes, edges.difference({edge})
            else:
                raise ValueError("prepared score requires a valid structural action")
            self.table[action] = self.predictor._compile((changed_nodes, changed_edges))
        return self.predictor._weighted_score(self.table[action], self.nodes)


__all__ = ["FastComponentSettlement", "TopologyKey"]

# End inline: src/starnet/policy/fast_settlement_experiment.py

# Begin inline: src/starnet/policy/p8_experiment.py
"""P8 bounded public-state value-of-information rollout experiment.

The unobserved response assumption is explicitly ``r ~ Uniform(0.2, 1.5)``.
All counterfactual state stays in :class:`PredictiveState` and a dedicated
read-only projection; it is never written to the factual Blackboard.
"""


from dataclasses import dataclass
import hashlib
import json
import math
import random
from types import MappingProxyType
from typing import Literal, Mapping, MutableMapping



P8Mode = Literal["expected", "conservative", "audited"]
EvaluationCache = MutableMapping[tuple[object, ...], float]
_FAST_SETTLEMENT = FastComponentSettlement(max_topologies=128)


@dataclass(frozen=True)
class _ProjectedNode:
    w: float
    persona: str
    comm_left: int | None


@dataclass(frozen=True)
class _ProjectedBoard:
    nodes: Mapping[int, _ProjectedNode]
    edges: frozenset[tuple[int, int]]
    dead_nodes: frozenset[int]
    node_count: int

    @classmethod
    def from_state(cls, state: PredictiveState, node_count: int) -> "_ProjectedBoard":
        nodes = MappingProxyType({
            node_id: _ProjectedNode(node.w, node.persona, node.comm_left)
            for node_id, node in state.nodes.items()
        })
        return cls(nodes, frozenset(state.edges), frozenset(state.dead_nodes), node_count)

    @property
    def scanned_ids(self) -> frozenset[int]:
        return frozenset(self.nodes) | self.dead_nodes

    @property
    def shielded_ids(self) -> frozenset[int]:
        return self.dead_nodes


@dataclass(frozen=True)
class P8Decision:
    action: Action | None
    baseline_action: Action | None
    source: str
    compared_actions: tuple[Action, ...]
    paired_deltas: tuple[float, ...]
    mean_delta: float
    minimum_delta: float
    rollouts: int
    proposed_action: Action | None = None
    audit_paired_deltas: tuple[float, ...] = ()
    audit_mean_delta: float = 0.0
    audit_minimum_delta: float = 0.0

    @property
    def deviated(self) -> bool:
        return self.action is not None and self.action != self.baseline_action


def _action_key(action: Action) -> tuple[object, ...]:
    return (action.kind, action.target_node_1, action.target_node_2, action.prompt_id)


def _public_state_payload(board: Blackboard | _ProjectedBoard) -> dict[str, object]:
    return {
        "node_count": board.node_count,
        "nodes": [[node_id, node.w, node.persona, node.comm_left]
                  for node_id, node in sorted(board.nodes.items())],
        "edges": [list(edge) for edge in sorted(board.edges)],
        "dead_nodes": sorted(board.dead_nodes),
    }


def public_board_salt(board: Blackboard) -> str:
    """Hash a complete initial public board without events or private data."""
    if board.node_count is None or len(board.scanned_ids) != board.node_count:
        raise ValueError("P8 salt requires a completely scanned public board")
    payload = json.dumps(_public_state_payload(board), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_digest(board: Blackboard | _ProjectedBoard) -> str:
    payload = json.dumps(_public_state_payload(board), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _response_fn(board: Blackboard | _ProjectedBoard, observed: Mapping[int, float]):
    estimate = _response if public_positive_graph_gate_closed(board) else public_response
    return lambda node_id, node, turn: estimate(
        node_id, node.persona, turn, observed, DEFAULT_CALIBRATION_PROFILE,
    )


def _greedy_candidates(board: Blackboard | _ProjectedBoard, budget: float,
                       observed: Mapping[int, float], *, fast: bool = True):
    planner = ExperimentalPublicGreedyPlanner(
        _response_fn(board, observed),
        candidate_limit=len(board.edges) + 2 * len(board.nodes) + 1,
        min_observed_responses=0,
        structure_roi_margin=1.0,
    )
    if fast:
        planner.predictor = _FAST_SETTLEMENT
    return planner.candidates(board, budget, observed_response_count=len(observed))


def _scenario_factor(salt: str, node_id: int, scenario: int) -> float:
    """Return mean plus six fixed antithetic Uniform(0.2, 1.5) pairs."""
    if scenario == 0:
        return 0.85
    if scenario not in range(1, 13):
        raise ValueError("P8 scenario must be in 0..12")
    pair = (scenario - 1) // 2
    digest = hashlib.sha256(f"{salt}:{node_id}:{pair}".encode("ascii")).digest()
    base = random.Random(int.from_bytes(digest[:8], "big")).uniform(0.2, 1.5)
    return base if scenario % 2 else 1.7 - base


def _rollout(
    board: Blackboard, budget: float, observed: Mapping[int, float], first_action: Action,
    remaining_steps: int, *, scenario: int, salt: str,
) -> float:
    if remaining_steps < 0 or not math.isfinite(budget) or budget < 0:
        raise ValueError("invalid P8 rollout resources")
    state = PredictiveState.from_blackboard(board)
    visible = dict(observed)
    pending: Action | None = first_action
    for _ in range(remaining_steps):
        projected = _ProjectedBoard.from_state(state, board.node_count or len(board.nodes))
        if pending is None:
            candidates = _greedy_candidates(projected, budget, visible)
            if not candidates:
                break
            action = candidates[0].action
        else:
            action, pending = pending, None
        if not is_legal_action(action, projected, budget):
            raise ValueError("illegal P8 rollout action")
        delta = None
        if action.kind == "comm":
            node = state.nodes[action.target_node_1]
            if node.comm_left is None:
                raise ValueError("missing public communication count")
            turn = 4 - node.comm_left
            first = visible.get(action.target_node_1)
            if first is None:
                first = 15.0 * _scenario_factor(salt, action.target_node_1, scenario)
                # The simulated policy learns this response only now, after
                # the successful hypothetical action on its own path.
                visible[action.target_node_1] = first
            delta = first * (0.5 ** (turn - 1))
        state = state.apply(action, delta)
        budget -= action_cost(action)
    score = float(_FAST_SETTLEMENT.score(state))
    if not math.isfinite(score):
        raise ValueError("nonfinite P8 rollout score")
    return score


def _candidate_domain(
    board: Blackboard, budget: float, observed: Mapping[int, float], remaining_steps: int,
) -> tuple[tuple[Action, str], ...]:
    ranked = _greedy_candidates(board, budget, observed)
    if not ranked:
        return ()
    candidates: list[tuple[Action, str]] = [(ranked[0].action, "public_greedy")]
    plan = budget_plan(board, budget, _response_fn(board, observed),
                       remaining_steps=remaining_steps, depth=1, width=2)
    if plan.actions and plan.actions[0].kind in {"cut", "shield"}:
        candidates.append((plan.actions[0], "p7_budget_structure"))
    structures = [item for item in ranked if item.action.kind in {"cut", "shield"}]
    if structures:
        best = min(structures, key=lambda item: (-item.score, item.candidate_id))
        candidates.append((best.action, "immediate_structure_gain"))
    untried = [item for item in ranked if item.action.kind == "comm"
               and item.action.target_node_1 not in observed]
    if untried:
        best = min(untried, key=lambda item: (-item.roi, -item.score, item.candidate_id))
        candidates.append((best.action, "untried_comm_roi"))
    unique: list[tuple[Action, str]] = []
    seen: set[Action] = set()
    for action, source in candidates:
        if action not in seen:
            seen.add(action)
            unique.append((action, source))
    return tuple(unique[:4])


def choose_p8_action(
    board: Blackboard, budget: float, observed: Mapping[int, float], *,
    remaining_steps: int, salt: str, mode: P8Mode,
    evaluation_cache: EvaluationCache | None = None,
) -> P8Decision:
    """Run a fixed mean screen, then five paired scenarios for one winner.

    This sequential screen is a bounded decision rule, not an unbiased
    estimate or a confidence interval.
    """
    if mode not in ("expected", "conservative", "audited"):
        raise ValueError("unknown P8 mode")
    if remaining_steps < 0 or not math.isfinite(budget) or budget < 0 or len(salt) != 64:
        raise ValueError("invalid P8 decision inputs")
    if any(not math.isfinite(float(value)) for value in observed.values()):
        raise ValueError("nonfinite public response")
    if remaining_steps == 0:
        return P8Decision(None, None, "none", (), (), 0.0, 0.0, 0)
    domain = _candidate_domain(board, budget, observed, remaining_steps)
    if not domain:
        return P8Decision(None, None, "none", (), (), 0.0, 0.0, 0)
    baseline = domain[0][0]
    if len(domain) == 1:
        return P8Decision(baseline, baseline, "public_greedy", (baseline,), (), 0.0, 0.0, 0)
    cache = evaluation_cache if evaluation_cache is not None else {}
    digest = _state_digest(board)
    observed_key = tuple(sorted((node, float(value)) for node, value in observed.items()))
    rollouts = 0

    def score(action: Action, scenario: int) -> float:
        nonlocal rollouts
        key = (digest, float(budget), remaining_steps, observed_key, salt,
               _action_key(action), scenario)
        if key not in cache:
            cache[key] = _rollout(board, budget, observed, action, remaining_steps,
                                  scenario=scenario, salt=salt)
            rollouts += 1
        value = float(cache[key])
        if not math.isfinite(value):
            raise ValueError("nonfinite cached P8 score")
        return value

    baseline_mean = score(baseline, 0)
    screened_structures: list[tuple[float, tuple[object, ...], Action, str]] = []
    untried_comm: tuple[Action, str] | None = None
    for action, source in domain[1:]:
        delta = score(action, 0) - baseline_mean
        if source == "untried_comm_roi":
            # A constant mean response deliberately removes the value of
            # learning. Preserve this candidate for the heterogeneous paired
            # scenarios even when its mean-only screen is neutral.
            untried_comm = (action, source)
        elif action.kind in {"cut", "shield"} and delta > 1e-9:
            screened_structures.append((-delta, _action_key(action), action, source))
    finalists: list[tuple[Action, str]] = []
    if screened_structures:
        _, _, action, source = min(screened_structures)
        finalists.append((action, source))
    if untried_comm is not None and untried_comm[0] not in {item[0] for item in finalists}:
        finalists.append(untried_comm)
    if not finalists:
        return P8Decision(baseline, baseline, "public_greedy",
                          tuple(action for action, _ in domain), (), 0.0, 0.0, rollouts)
    accepted: list[tuple[float, tuple[object, ...], Action, str,
                         tuple[float, ...], float, float]] = []
    for candidate, source in finalists:
        deltas = tuple(score(candidate, scenario) - score(baseline, scenario)
                       for scenario in range(5))
        mean_delta = sum(deltas) / len(deltas)
        minimum = min(deltas)
        if mean_delta > 1e-9 and (mode == "expected" or minimum >= -1e-9):
            accepted.append((-mean_delta, _action_key(candidate), candidate, source,
                             deltas, mean_delta, minimum))
    if not accepted:
        return P8Decision(baseline, baseline, "public_greedy",
                          tuple(action for action, _ in domain), (), 0.0, 0.0, rollouts)
    _, _, winner, source, deltas, mean_delta, minimum = min(accepted)
    compared = tuple(action for action, _ in domain)
    if mode != "audited":
        return P8Decision(winner, baseline, source, compared, deltas,
                          mean_delta, minimum, rollouts, proposed_action=winner)
    audit_deltas = tuple(score(winner, scenario) - score(baseline, scenario)
                         for scenario in range(5, 13))
    audit_mean = sum(audit_deltas) / len(audit_deltas)
    audit_minimum = min(audit_deltas)
    audit_passed = audit_mean > 1e-9 and audit_minimum >= -1e-9
    return P8Decision(
        winner if audit_passed else baseline, baseline,
        source if audit_passed else "public_greedy", compared,
        deltas, mean_delta, minimum, rollouts, proposed_action=winner,
        audit_paired_deltas=audit_deltas, audit_mean_delta=audit_mean,
        audit_minimum_delta=audit_minimum,
    )


__all__ = ["EvaluationCache", "P8Decision", "P8Mode", "choose_p8_action", "public_board_salt"]

# End inline: src/starnet/policy/p8_experiment.py

# Begin inline: src/starnet/policy/p8_qualification.py
"""Local mean-objective qualification, not per-family noninferiority.

New repetitions 701--705 passed the preregistered mean/composition criterion;
the earlier 601--605 strict gate remains failed. Unqualified requests close.
"""


P8_CERTIFIED_MODE: str | None = "conservative"
P8_GATE_REPORT_SHA256: str | None = "0594442f917eacbffe553bb7499b832d31a8b8fde12ba47c6479573ec464850c"


def qualified_p8_mode(requested: object) -> str | None:
    if (P8_CERTIFIED_MODE in ("conservative", "audited")
            and requested == P8_CERTIFIED_MODE
            and isinstance(P8_GATE_REPORT_SHA256, str)
            and len(P8_GATE_REPORT_SHA256) == 64):
        return P8_CERTIFIED_MODE
    return None

# End inline: src/starnet/policy/p8_qualification.py

# Begin inline: src/starnet/policy/adaptive.py
"""B5 adaptive exploration primitives.

The scenario layer is deliberately small and explicit.  A scenario is a
possible completion of unknown facts, never a replacement for Blackboard
facts.  If validation is unavailable, callers must use the deterministic
full-scan scout.
"""


from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
import random

import networkx as nx



@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    state: PredictiveState
    observations: Mapping[int, Mapping[str, object]]
    weight: float = 1.0


@dataclass(frozen=True)
class ScenarioProfile:
    """Independently validated hidden-state hypotheses for B5."""

    scenarios: tuple[Scenario, ...] = ()
    gate_passed: bool = False
    independent_validation_passed: bool = False

    @property
    def verified(self) -> bool:
        return (
            self.gate_passed and self.independent_validation_passed
            and bool(self.scenarios)
            and all(math.isfinite(float(item.weight)) and item.weight >= 0 for item in self.scenarios)
            and sum(item.weight for item in self.scenarios) > 0
        )

    @classmethod
    def from_states(cls, states: Sequence[PredictiveState]) -> "ScenarioProfile":
        scenarios = tuple(
            Scenario(str(index), state, {}, 1.0) for index, state in enumerate(states)
        )
        return cls(scenarios, True, True)

    def normalized(self) -> tuple[tuple[Scenario, float], ...]:
        total = sum(max(0.0, float(item.weight)) for item in self.scenarios)
        if not self.verified or total <= 0:
            return ()
        return tuple((item, float(item.weight) / total) for item in self.scenarios)

    def is_consistent(self, board: Blackboard) -> bool:
        """Reject scenarios contradicting any observed node, edge, or non-edge."""
        if not self.verified:
            return False
        for scenario, _weight in self.normalized():
            # A public unavailable/shielded result is a fact, not a latent
            # variable.  A scenario retaining that node (or an incident edge)
            # cannot be used for a later VOI calculation.
            if (
                board.dead_nodes.intersection(scenario.state.nodes)
                or not board.dead_nodes.issubset(scenario.state.dead_nodes)
                or any(board.dead_nodes.intersection(edge) for edge in scenario.state.edges)
                or board.dead_nodes.intersection(scenario.observations)
            ):
                return False
            for node_id, observed in board.nodes.items():
                possible = scenario.state.nodes.get(node_id)
                if possible is None:
                    return False
                if (
                    not math.isclose(possible.w, observed.w, abs_tol=1e-9)
                    or possible.persona != observed.persona
                    or possible.comm_left != observed.comm_left
                ):
                    return False
            if not board.edges.issubset(scenario.state.edges):
                return False
            if any(edge in scenario.state.edges for edge in board.confirmed_non_edges):
                return False
            # A recorded scan response is part of the scenario's hidden state;
            # accepting a payload that contradicts it would fabricate VOI.
            for node_id, payload in scenario.observations.items():
                possible = scenario.state.nodes.get(node_id)
                if possible is None or not _observation_matches_state(node_id, payload, scenario.state):
                    return False
        return True


@dataclass(frozen=True)
class ScanValue:
    node_id: int
    voi: float
    evidence_ids: tuple[str, ...]


def _apply_observation(state: PredictiveState, node_id: int, payload: Mapping[str, object]) -> PredictiveState | None:
    raw_w = payload.get("w")
    persona = payload.get("persona")
    raw_comm = payload.get("comm_left")
    neighbors = payload.get("neighbors")
    if not isinstance(raw_w, (int, float)) or isinstance(raw_w, bool) or not math.isfinite(float(raw_w)):
        return None
    if not isinstance(persona, str) or not isinstance(neighbors, list):
        return None
    if raw_comm is not None and (not isinstance(raw_comm, int) or isinstance(raw_comm, bool)):
        return None
    nodes = {key: NodeState(value.w, value.persona, value.comm_left) for key, value in state.nodes.items()}
    nodes[node_id] = NodeState(float(raw_w), persona, raw_comm)
    edges = {edge for edge in state.edges if node_id not in edge}
    for neighbor in neighbors:
        if isinstance(neighbor, int) and not isinstance(neighbor, bool) and neighbor != node_id:
            edges.add((min(node_id, neighbor), max(node_id, neighbor)))
    return PredictiveState(nodes, edges, set(state.dead_nodes))


def _scenario_observation(scenario: Scenario, node_id: int) -> Mapping[str, object] | None:
    """Return the fixed scan result implied by one complete scenario."""
    recorded = scenario.observations.get(node_id)
    if recorded is not None:
        return recorded
    node = scenario.state.nodes.get(node_id)
    if node is None or node_id in scenario.state.dead_nodes:
        return None
    return {
        "w": node.w,
        "persona": node.persona,
        "comm_left": node.comm_left,
        "neighbors": sorted(
            right if left == node_id else left
            for left, right in scenario.state.edges
            if node_id in (left, right)
        ),
    }


def _observation_matches_state(
    node_id: int, payload: Mapping[str, object], state: PredictiveState
) -> bool:
    """Check that a recorded scenario observation does not contradict state."""
    expected = _scenario_observation(Scenario("", state, {}, 1.0), node_id)
    if expected is None:
        return False
    return (
        payload.get("w") == expected["w"]
        and payload.get("persona") == expected["persona"]
        and payload.get("comm_left", expected["comm_left"]) == expected["comm_left"]
        and isinstance(payload.get("neighbors"), list)
        and sorted(payload["neighbors"]) == expected["neighbors"]
    )


def evaluate_scan_voi(
    board: Blackboard,
    node_id: int,
    profile: ScenarioProfile,
    value_fn: Callable[[PredictiveState], float],
    *,
    branch_value_fn: Callable[[PredictiveState], float] | None = None,
    scan_cost: float = 0.5,
) -> ScanValue:
    """Evaluate a fixed prior and its observation branches without resampling.

    ``value_fn`` evaluates the current public state.  ``branch_value_fn`` (or
    ``value_fn`` when omitted) evaluates that same state after one fixed scan
    result; callers normally give it the reduced budget/step envelope.  Thus
    the branch can rerun a bounded legal planner without peeking at the
    scenario's full hidden state.  Set ``scan_cost`` to zero only when the
    branch function already receives reduced resources.
    """
    if not profile.is_consistent(board) or not board.can_scan(node_id):
        return ScanValue(node_id, -math.inf, ())
    before_state = PredictiveState.from_blackboard(board)
    before = float(value_fn(before_state))
    if not math.isfinite(before):
        return ScanValue(node_id, -math.inf, ())
    weighted_after = 0.0
    evidence: list[str] = []
    for scenario, weight in profile.normalized()[:8]:
        observation = _scenario_observation(scenario, node_id)
        after_state = _apply_observation(before_state, node_id, observation) if observation else None
        if after_state is None:
            # A scenario without an observation does not create artificial VOI.
            after = before
        else:
            after = float((branch_value_fn or value_fn)(after_state))
            evidence.append(f"scenario:{scenario.scenario_id}:scan:{node_id}")
        if not math.isfinite(before) or not math.isfinite(after):
            return ScanValue(node_id, -math.inf, tuple(evidence))
        weighted_after += weight * after
    # The value function is evaluated on the same scenario before and after;
    # charge the information action exactly once here.
    return ScanValue(node_id, weighted_after - before - scan_cost, tuple(evidence))


class AdaptiveScout:
    """Frontier/blind mixed scout with deterministic pseudo-random starts."""

    def __init__(self, node_count: int, *, initial_count: int, seed: int = 20260905) -> None:
        if node_count <= 0 or initial_count <= 0:
            raise ValueError("node_count and initial_count must be positive")
        self.node_count = node_count
        self.initial_count = min(node_count, initial_count)
        self._rng = random.Random(seed)
        self._initial = iter(sorted(self._rng.sample(range(1, node_count + 1), self.initial_count)))
        self.scan_count = 0

    @property
    def exhausted(self) -> bool:
        return self.scan_count >= self.node_count

    def _rank(self, board: Blackboard) -> list[int]:
        unknown = [node for node in range(1, self.node_count + 1) if board.can_scan(node)]
        frontier = board.frontier_ids
        graph = nx.Graph()
        graph.add_edges_from(board.edges)
        seen_components: dict[int, int] = {}
        for component_id, component in enumerate(nx.connected_components(graph)):
            for node in component:
                seen_components[node] = component_id
        coverage: dict[int, int] = {}
        for node in board.nodes:
            component = seen_components.get(node, node)
            coverage[component] = coverage.get(component, 0) + 1
        def key(node: int) -> tuple[int, int, int, int]:
            adjacent_seen = sum(node in edge for edge in board.edges)
            region = seen_components.get(node, node)
            return (0 if node in frontier else 1, -adjacent_seen, coverage.get(region, 0), node)
        return sorted(unknown, key=key)

    def candidate_ids(self, board: Blackboard) -> tuple[int, ...]:
        """Expose the bounded frontier/blind pool without consuming a scan."""
        return tuple(self._rank(board))

    def next_action(self, board: Blackboard, *, voi: Mapping[int, float] | None = None) -> Action | None:
        while True:
            try:
                node_id = next(self._initial)
            except StopIteration:
                break
            if board.can_scan(node_id):
                self.scan_count += 1
                return Action("scan", node_id)
        choices = self._rank(board)
        if voi:
            choices = sorted(choices, key=lambda node: (-float(voi.get(node, -math.inf)), node))
        if not choices:
            return None
        self.scan_count += 1
        return Action("scan", choices[0])


__all__ = ["AdaptiveScout", "ScanValue", "Scenario", "ScenarioProfile", "evaluate_scan_voi"]

# End inline: src/starnet/policy/adaptive.py

# Begin inline: src/starnet/runtime/stage.py
"""Explicit contest-stage contract.

The stage is deployment configuration, never an observation inferred from a
budget response or from the ids that happened to be scanned.  Keeping this in
one small module makes the resource envelope reviewable and testable.
"""


from dataclasses import dataclass
from enum import Enum


class ContestStage(str, Enum):
    PRELIMINARY = "preliminary"
    FINAL = "final"


@dataclass(frozen=True)
class StageSpec:
    name: ContestStage
    node_count: int
    budget_units: int
    step_limit: int
    llm_limit: int
    safe_step_limit: int
    safe_llm_limit: int

    @property
    def budget(self) -> float:
        return self.budget_units / 2.0


PRELIMINARY = StageSpec(ContestStage.PRELIMINARY, 50, 200, 120, 120, 117, 115)
FINAL = StageSpec(ContestStage.FINAL, 100, 400, 250, 250, 247, 245)


def stage_spec(value: ContestStage | str) -> StageSpec:
    stage = ContestStage(value)
    return PRELIMINARY if stage is ContestStage.PRELIMINARY else FINAL


__all__ = ["ContestStage", "FINAL", "PRELIMINARY", "StageSpec", "stage_spec"]

# End inline: src/starnet/runtime/stage.py

# Begin inline: src/starnet/runtime/controller.py
"""Deterministic scan, analysis, and batch execution state machine.

The controller is independent of ``casevo``. A local caller may attach a
``RuntimeTrace`` after constructing its model and before the first ``step``;
without that explicit injection all trace paths are inert.
"""


from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence



MAX_LLM_CALLS = 3
MAX_BATCH_ACTIONS = 10
MAX_CONSECUTIVE_INVALID = 3


class ControllerState(str, Enum):
    """Explicit controller state, observable by the submission host."""

    INIT = "INIT"
    SCAN_ALL = "SCAN_ALL"
    ANALYZE = "ANALYZE"
    PLAN_BATCH = "PLAN_BATCH"
    PLAN_CMG = "PLAN_CMG"
    EXECUTE = "EXECUTE"
    REANALYZE = "REANALYZE"
    STOP = "STOP"


class StopReason(str, Enum):
    """De-identified reasons for normal controller termination."""

    NO_CANDIDATES = "no_candidates"
    INSUFFICIENT_BUDGET = "insufficient_budget"
    NO_VALID_ACTIONS = "no_valid_actions"
    STATE_GUARD = "state_guard"
    STEP_LIMIT = "step_limit"
    RUNNER_ERROR = "runner_error"
    NO_POSITIVE_GAIN = "no_positive_gain"


class DeterministicScout:
    """Scan fixed node IDs in order and never call an LLM."""

    def __init__(self, node_count: int) -> None:
        if node_count <= 0:
            raise ValueError("node_count 必须为正整数")
        self.node_count = node_count
        self._next_node_id = 1

    @property
    def exhausted(self) -> bool:
        return self._next_node_id > self.node_count

    def next_action(self, blackboard: Blackboard) -> Action | None:
        """Return the next unknown ID scan; known IDs are not requested again."""
        while self._next_node_id <= self.node_count:
            node_id = self._next_node_id
            self._next_node_id += 1
            if blackboard.can_scan(node_id):
                return Action("scan", node_id)
        return None


class GraphAnalyst:
    """Thin role wrapper retained for a clear single-file submission boundary."""

    def analyze(self, blackboard: Blackboard) -> GraphAnalysis:
        return analyze_graph(blackboard)

    def generate_candidates(
        self,
        analysis: GraphAnalysis,
        blackboard: Blackboard,
        budget: float,
        failed_actions: set[str],
        config: PolicyConfig,
    ) -> list[Candidate]:
        return generate_candidates(analysis, blackboard, budget, failed_actions, config)


LlmRanker = Callable[[dict[str, Any]], object]


def _action_name(action: Any) -> str:
    if action is None:
        return "stop"
    if getattr(action, "kind", None) == "comm":
        return f"comm:{action.target_node_1}:{action.prompt_id}"
    if getattr(action, "kind", None) == "cut":
        return f"cut:{action.target_node_1}-{action.target_node_2}"
    return f"{action.kind}:{action.target_node_1}"


@dataclass(frozen=True)
class BatchPlan:
    """A candidate queue plus the exact source of its ordering."""

    candidate_ids: tuple[str, ...]
    source: str
    fallback_reason: str | None = None
    request_payload: Mapping[str, Any] | None = None
    raw_response: object | None = None
    parsed_candidate_ids: tuple[str, ...] = ()
    error: Mapping[str, str] | None = None

    @property
    def used_llm(self) -> bool:
        """Compatibility alias for the prior two-state plan API."""
        return self.source == "llm"


@dataclass(frozen=True)
class QueueValidation:
    candidate_ids: tuple[str, ...]
    discarded: tuple[dict[str, str], ...]


class BatchCommander:
    """Use an LLM only to order Python-validated candidates, with fallback."""

    def __init__(
        self,
        llm_ranker: LlmRanker | None = None,
        *,
        config: PolicyConfig = DEFAULT_POLICY_CONFIG,
        contest_llm_limit: int | None = None,
    ) -> None:
        self.llm_ranker = llm_ranker
        self.config = config
        self.max_llm_calls = min(
            config.max_llm_calls,
            contest_llm_limit if contest_llm_limit is not None else config.max_llm_calls,
        )
        self.llm_calls = 0

    @property
    def can_request_llm(self) -> bool:
        return (
            self.config.llm_schedule is not LLMSchedule.OFF
            and self.llm_ranker is not None
            and self.llm_calls < self.max_llm_calls
        )

    def preview_payload(
        self,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
        state_version: int = 0,
    ) -> dict[str, Any]:
        """Build the exact payload for the next request without consuming quota."""
        return self._build_payload(candidates, budget, analysis, self.llm_calls + 1, state_version)

    def plan(
        self,
        *,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
        request_payload: Mapping[str, Any] | None = None,
        state_version: int = 0,
    ) -> BatchPlan:
        candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
        fallback = tuple(select_deterministic_batch(candidates, budget, MAX_BATCH_ACTIONS, config=self.config))
        if not candidate_map:
            return BatchPlan(fallback, "deterministic_fallback", "no_candidates")
        if self.config.llm_schedule is LLMSchedule.OFF or self.llm_ranker is None:
            return BatchPlan(fallback, "deterministic_fallback", "no_llm_ranker")
        if self.llm_calls >= self.max_llm_calls:
            return BatchPlan(fallback, "quota_exhausted", "quota_exhausted")

        # Quota is consumed before the external call, including a timeout.
        self.llm_calls += 1
        payload = dict(request_payload or self._build_payload(candidates, budget, analysis, self.llm_calls, state_version))
        try:
            raw_response = self.llm_ranker(payload)
        except Exception as exc:
            return BatchPlan(
                fallback,
                "deterministic_fallback",
                "exception",
                payload,
                error=safe_error(exc),
            )

        parsed = self._parse_response(raw_response, candidate_map, budget, payload)
        if parsed.accepted:
            return BatchPlan(
                parsed.candidate_ids,
                "llm",
                request_payload=payload,
                raw_response=raw_response,
                parsed_candidate_ids=parsed.candidate_ids,
            )
        return BatchPlan(
            parsed.candidate_ids,
            "deterministic_fallback",
            parsed.fallback_reason,
            payload,
            raw_response,
            parsed.candidate_ids,
        )

    def _build_payload(
        self,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
        llm_call_number: int,
        state_version: int,
    ) -> dict[str, Any]:
        graph = analysis.graph
        negative_nodes = sorted(
            node_id
            for node_id, metrics in analysis.node_metrics.items()
            if metrics.danger > 0
        )
        positive_nodes = sorted(
            node_id
            for node_id, metrics in analysis.node_metrics.items()
            if metrics.positive_influence > 0
        )
        return {
            "stage": ControllerState.PLAN_BATCH.value,
            "state_version": state_version,
            "mode": "single_action",
            "budget": budget,
            "llm_calls": llm_call_number,
            "graph": {
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(),
                "community_count": analysis.community_count,
                "negative_nodes": negative_nodes,
                "positive_nodes": positive_nodes,
            },
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "action": asdict(candidate.action),
                    "cost": action_cost(candidate.action),
                    "priority": candidate.priority,
                    "score": candidate.score,
                    "roi": candidate.roi,
                    "reason": candidate.reason,
                    "evidence_ids": list(candidate.evidence_ids or (candidate.candidate_id,)),
                }
                for candidate in candidates
            ],
            "candidate_ids": [candidate.candidate_id for candidate in candidates],
        }

    def _parse_response(
        self,
        raw_response: object,
        candidate_map: Mapping[str, Candidate],
        budget: float,
        payload: Mapping[str, Any],
    ) -> LlmParseResult:
        """Accept the current one-candidate protocol, then legacy fixtures.

        The submission Commander emits the strict form.  Supporting the old
        batch form here keeps historical local experiments reproducible without
        allowing it to weaken the submission's decision boundary.
        """
        fallback = tuple(select_deterministic_batch(candidate_map.values(), budget, config=self.config))
        if isinstance(raw_response, Mapping) and {
            "state_version", "mode", "candidate_id", "reason_code", "evidence_ids"
        } == set(raw_response):
            candidate_id = raw_response.get("candidate_id")
            evidence_ids = raw_response.get("evidence_ids")
            if raw_response.get("state_version") != payload.get("state_version"):
                return LlmParseResult(fallback, False, "stale_state_version")
            if not isinstance(candidate_id, str) or candidate_id not in candidate_map:
                return LlmParseResult(fallback, False, "unknown_candidate")
            selected = candidate_map[candidate_id]
            allowed_evidence = set(selected.evidence_ids) or {candidate_id}
            if (
                not isinstance(evidence_ids, list)
                or not evidence_ids
                or any(not isinstance(item, str) or item not in allowed_evidence for item in evidence_ids)
            ):
                return LlmParseResult(fallback, False, "invalid_evidence_ids")
            return LlmParseResult((candidate_id,), True)
        return parse_llm_batch_detailed(raw_response, candidate_map, budget, config=self.config)


class RuntimeController:
    """V0 state machine plus fail-closed V1 CMG; one public action per step."""

    def __init__(
        self,
        env: StarNetEnvironment,
        llm_ranker: LlmRanker | None = None,
        *,
        initial_budget: float | None = None,
        node_count: int | None = None,
        stage: ContestStage | str | None = None,
        blackboard: Blackboard | None = None,
        config: PolicyConfig = DEFAULT_POLICY_CONFIG,
        calibration_profile: CalibrationProfile = DEFAULT_CALIBRATION_PROFILE,
        scenario_profile: ScenarioProfile | None = None,
    ) -> None:
        self.env = env
        # Stage selection is an explicit deployment input. ``node_count`` is a
        # test seam only; the submission never supplies it and never infers a
        # stage from a remote budget response.
        # The submission always supplies an explicit stage.  A test/development
        # caller that explicitly supplies the official 100-node count gets the
        # matching final envelope; no budget, scanned id, or observation is
        # ever used to infer a stage.
        if stage is None:
            stage = ContestStage.FINAL if node_count == 100 else ContestStage.PRELIMINARY
        self.stage: StageSpec = stage_spec(stage)
        selected_node_count = self.stage.node_count if node_count is None else node_count
        self.blackboard = blackboard if blackboard is not None else Blackboard(selected_node_count)
        self.initial_budget = float(
            env.get_remaining_budget() if initial_budget is None else initial_budget
        )
        self.node_count = selected_node_count
        self.blackboard.set_budget(self.initial_budget)
        self.config = config
        self._safe_step_limit = config.max_steps if config.max_steps is not None else self.stage.safe_step_limit
        self.calibration_profile = calibration_profile
        self.policy_mode = config.policy_mode
        self.effective_policy_mode = config.policy_mode
        self.scenario_profile = scenario_profile
        self.response_ledger = ResponseLedger()
        self.response_estimates: dict[int, float] = {}
        self.cmg_candidate: ScoredCandidate | None = None
        self.cmg_fallback_reason: str | None = None
        self._b5_enabled = (
            config.policy_mode is PolicyMode.B5_ADAPTIVE
            and calibration_profile.scenario_eligible
            and scenario_profile is not None
            and scenario_profile.verified
            and scenario_profile.is_consistent(self.blackboard)
        )
        if self._b5_enabled:
            initial_count = (
                config.adaptive_initial_final if self.stage is stage_spec(ContestStage.FINAL)
                else config.adaptive_initial_preliminary
            )
            self.scout = AdaptiveScout(self.node_count, initial_count=initial_count)
        else:
            # Invalid/missing scenario qualification intentionally means B5
            # scans exactly as the B4 full-scan fallback.
            self.scout = DeterministicScout(self.node_count)
        self.analyst = GraphAnalyst()
        self.structural_plans: dict[str, PlanCandidate] = {}
        self.structural_planner: StructuralPlanner | None = None
        self._event_llm_pending = config.llm_schedule is LLMSchedule.EVENT
        # The experiment may forbid LLM use even when the official model has a ranker.
        self.commander = BatchCommander(
            # P3 has two separate qualifications: B5's scenario profile and
            # the LLM ablation.  Until the scenario gate passes, B5 must be
            # an exact deterministic fallback rather than quietly spending
            # LLM quota to reorder B1 candidates.
            llm_ranker if config.max_llm_calls and (
                config.policy_mode is not PolicyMode.B5_ADAPTIVE or self._b5_enabled
            ) else None,
            config=config,
            contest_llm_limit=self.stage.llm_limit,
        )
        self._llm_scan_enabled = (
            config.policy_mode is PolicyMode.PUBLIC_GREEDY
            and self.commander.can_request_llm
        )
        self.state = ControllerState.INIT
        self.analysis: GraphAnalysis | None = None
        self.candidates: dict[str, Candidate] = {}
        self.queue: list[str] = []
        self.llm_accepted = 0
        self.llm_fallbacks = 0
        # Store both plan IDs and immutable public Action identities.  A B4
        # plan may share a first action with other plans, so a rejected action
        # must suppress every such plan on the next replan.
        self.failed_actions: set[str | Action] = set()
        self.consecutive_invalid = 0
        self.last_action_attempted = False
        self.last_action_succeeded: bool | None = None
        self.last_action_error: str | None = None
        self.action_attempts = 0
        self.action_successes = 0
        self.action_failures = 0
        self.stop_reason: StopReason | None = None
        self._trace: RuntimeTrace = NullRuntimeTrace()
        self._step_number = 0
        self._last_trace_budget_after: float | None = None
        self._last_step_action: dict[str, Any] | None = None
        self._last_step_action_result = "idle"
        self._last_step_selected_ids: list[str] = []

    @property
    def llm_calls(self) -> int:
        return self.commander.llm_calls

    @property
    def stopped(self) -> bool:
        return self.state is ControllerState.STOP

    @property
    def step_number(self) -> int:
        return self._step_number

    def attach_trace(self, trace: RuntimeTrace) -> None:
        """Attach optional local diagnostics before the first controller step."""
        self._trace = trace
        self._emit(
            "run.started",
            self.initial_budget,
            self.initial_budget,
            {
                "node_count": self.scout.node_count,
                "initial_budget": self.initial_budget,
                "max_llm_calls": self.commander.max_llm_calls,
                "safety_step_limit": self._safe_step_limit,
                "max_batch_actions": MAX_BATCH_ACTIONS,
                "policy_mode": self.policy_mode.value,
                "calibration_profile_hash": self.calibration_profile.profile_hash or None,
            },
        )

    def stop_for_step_limit(self) -> None:
        """Record a local runner's explicit safety cap as a normal stop event."""
        if not self.stopped:
            self._stop(StopReason.STEP_LIMIT, self._current_budget())

    def stop_for_runner_error(self) -> None:
        """Record a local runner abort without relying on a private environment API."""
        if not self.stopped:
            self._stop(StopReason.RUNNER_ERROR, self._current_budget())

    def record_evaluation(self, score: object, *, budget_before: float | None = None) -> None:
        """Let a local runner append the public evaluation result to the trace."""
        if not self._trace.enabled:
            return
        before = self._current_budget() if budget_before is None else budget_before
        after = self._trace_budget_after(before)
        self._emit(
            "evaluation.completed",
            before,
            after,
            {
                "score": score,
                "action_attempts": self.action_attempts,
                "action_successes": self.action_successes,
                "action_failures": self.action_failures,
                "remaining_budget": after,
                "stop_reason": self.stop_reason.value if self.stop_reason else None,
            },
        )

    def step(self) -> int:
        """Advance the state machine; diagnostics never control this flow."""
        # This consumes the last permitted outer call as a stop-only call.  It
        # leaves five calls of headroom beneath the published 120/250 limits.
        if self._step_number + 1 >= self._safe_step_limit:
            self._step_number += 1
            self._stop(StopReason.STEP_LIMIT, self._current_budget())
            return self._complete_step(1, self.state.value, self._current_budget())
        self._step_number += 1
        self.blackboard.outer_steps = self._step_number
        state_before = self.state.value
        budget_before = self._current_budget()
        self.last_action_attempted = False
        self.last_action_succeeded = None
        self.last_action_error = None
        self._last_trace_budget_after = None
        self._last_step_action = None
        self._last_step_action_result = "idle"
        self._last_step_selected_ids = []
        self._emit(
            "step.started",
            budget_before,
            budget_before,
            {"state_before": state_before, "action_attempts": self.action_attempts},
        )

        # State transitions have no environment action, so they may be consumed
        # in this dispatch slot until one public request is needed.
        for _ in range(8):
            if self.state is ControllerState.STOP:
                return self._complete_step(1, state_before, budget_before)

            budget = self._current_budget()
            if self.state is ControllerState.INIT:
                self._transition(ControllerState.SCAN_ALL, "initialized", budget)
                continue

            if self.state is ControllerState.SCAN_ALL:
                result = self._scan_next(budget)
                return self._complete_step(result, state_before, budget_before)

            if self.state is ControllerState.ANALYZE:
                self._refresh_candidates(budget, "analyze")
                if (
                    self.policy_mode is PolicyMode.B5_ADAPTIVE
                    and isinstance(self.scout, AdaptiveScout)
                    and not self.scout.exhausted
                    and not self.candidates
                ):
                    self._transition(ControllerState.SCAN_ALL, "adaptive_scan_has_no_positive_plan", budget)
                    continue
                if self.effective_policy_mode in {PolicyMode.B1_PERSUASION, PolicyMode.B2_INFLUENCE} and budget < 2.0:
                    self._stop(StopReason.INSUFFICIENT_BUDGET, budget)
                    continue
                if self._cmg_enabled:
                    self._transition(ControllerState.PLAN_CMG, "cmg_enabled", budget)
                elif self.candidates:
                    self._transition(ControllerState.PLAN_BATCH, "candidates_generated", budget)
                else:
                    self._stop(StopReason.NO_CANDIDATES, budget)
                continue

            if self.state is ControllerState.PLAN_BATCH:
                if not self.candidates or (
                    self.analysis is None
                    and self.effective_policy_mode not in {PolicyMode.B1_PERSUASION, PolicyMode.B2_INFLUENCE}
                ):
                    self._stop(StopReason.NO_CANDIDATES, budget)
                    continue
                self._create_plan(budget)
                if self.queue:
                    self._transition(ControllerState.EXECUTE, "validated_queue_available", budget)
                else:
                    self._stop(StopReason.NO_VALID_ACTIONS, budget)
                continue

            if self.state is ControllerState.PLAN_CMG:
                result = self._plan_cmg(budget)
                if result is not None:
                    return self._complete_step(result, state_before, budget_before)
                continue

            if self.state is ControllerState.EXECUTE:
                result = self._execute_next(budget)
                return self._complete_step(result, state_before, budget_before)

            if self.state is ControllerState.REANALYZE:
                self._refresh_candidates(budget, "reanalyze")
                if self.effective_policy_mode in {PolicyMode.B1_PERSUASION, PolicyMode.B2_INFLUENCE}:
                    # A successful communicate response changes the next-slot
                    # estimate. Rebuild the max-heap rather than consuming a
                    # stale batch planned before that feedback.
                    self.queue.clear()
                    if self.candidates:
                        self._transition(ControllerState.PLAN_BATCH, "persuasion_heap_refreshed", budget)
                    else:
                        self._stop(StopReason.NO_POSITIVE_GAIN, budget)
                    continue
                previous_queue = self.queue
                validation = self._valid_queue(previous_queue, budget)
                self.queue = list(validation.candidate_ids)
                self._emit_queue_revalidated("reanalysis", validation, budget)
                invalidated = len(previous_queue) - len(self.queue)
                if invalidated:
                    self.consecutive_invalid += invalidated
                if previous_queue and invalidated * 2 > len(previous_queue):
                    self.queue.clear()
                    self._emit(
                        "queue.revalidated",
                        budget,
                        budget,
                        {
                            "source": "reanalysis",
                            "enqueued_candidate_ids": [],
                            "discarded": [
                                {"candidate_id": candidate_id, "reason": "majority_invalidated"}
                                for candidate_id in validation.candidate_ids
                            ],
                        },
                    )
                if self.consecutive_invalid >= MAX_CONSECUTIVE_INVALID:
                    self.queue.clear()
                    self.consecutive_invalid = 0
                if self.queue:
                    self._transition(ControllerState.EXECUTE, "queue_revalidated", budget)
                elif self.candidates:
                    self._transition(ControllerState.PLAN_BATCH, "queue_empty_after_reanalysis", budget)
                else:
                    self._stop(StopReason.NO_VALID_ACTIONS, budget)
                continue

        self._stop(StopReason.STATE_GUARD, self._current_budget())
        return self._complete_step(1, state_before, budget_before)

    def _scan_next(self, budget: float) -> int:
        voi: dict[int, float] = {}
        if (
            isinstance(self.scout, AdaptiveScout)
            and self.scenario_profile is not None
            and self.calibration_profile.scenario_eligible
            and self.scenario_profile.verified
            and self.scenario_profile.is_consistent(self.blackboard)
            and self.scout.scan_count >= self.scout.initial_count
        ):
            # Keep one legal follow-up communication and one outer step after
            # an information action; scanning cannot consume the last useful
            # resource slot.
            if budget < 2.5 or self._safe_step_limit - self._step_number <= 1:
                self._stop(StopReason.INSUFFICIENT_BUDGET, budget)
                return 1
            predictor = SettlementPredictor(self.calibration_profile)
            remaining_steps = max(0, self._safe_step_limit - self._step_number)

            def future_value(state: PredictiveState, available_budget: float, available_steps: int) -> float:
                """Replan from a public observation branch under its resources."""
                branch_planner = StructuralPlanner(
                    self.calibration_profile,
                    ledger=self.response_ledger,
                    depth=self.config.structure_depth,
                    width=self.config.structure_width,
                    candidate_limit=self.config.structure_candidate_limit,
                )
                plans = branch_planner.plan_candidates(
                    state.to_blackboard(), available_budget, available_steps,
                    PolicyMode.B4_BEAM_STRUCTURE,
                )
                return plans[0].predicted_final_score if plans else predictor.score(state)

            for node_id in self.scout.candidate_ids(self.blackboard)[:8]:
                value = evaluate_scan_voi(
                    self.blackboard,
                    node_id,
                    self.scenario_profile,
                    lambda state: future_value(state, budget, remaining_steps),
                    branch_value_fn=lambda state: future_value(
                        state, budget - action_cost(Action("scan", node_id)), remaining_steps - 1
                    ),
                    scan_cost=0.0,
                )
                voi[node_id] = value.voi
            if not any(value > 0.0 for value in voi.values()):
                self._stop(StopReason.NO_POSITIVE_GAIN, budget)
                return 1
        if self._llm_scan_enabled:
            action = self._choose_public_scan(budget)
        elif isinstance(self.scout, AdaptiveScout):
            action = self.scout.next_action(self.blackboard, voi=voi)
        else:
            action = self.scout.next_action(self.blackboard)
        if action is None:
            self._transition(ControllerState.ANALYZE, "scan_exhausted", budget)
            self._emit("scan.completed", budget, budget, {"blackboard": self.blackboard.snapshot()})
            return 0
        if not is_legal_action(action, self.blackboard, budget):
            self._stop(StopReason.INSUFFICIENT_BUDGET, budget)
            return 1

        self._attempt_action(action, f"scan:{action.target_node_1}", budget)
        adaptive_checkpoint = isinstance(self.scout, AdaptiveScout) and self.scout.scan_count >= self.scout.initial_count
        if (
            (self._llm_scan_enabled and len(self.blackboard.scanned_ids) >= self.node_count)
            or (not self._llm_scan_enabled and self.scout.exhausted)
            or adaptive_checkpoint
        ):
            completed_budget = (
                self._last_trace_budget_after
                if self._last_trace_budget_after is not None
                else budget
            )
            if self.config.stop_after_scan:
                self._stop(StopReason.NO_CANDIDATES, completed_budget)
            else:
                self._transition(
                    ControllerState.ANALYZE,
                    "adaptive_initial_scan_complete" if adaptive_checkpoint and not self.scout.exhausted else "scan_complete",
                    completed_budget,
                )
            scanned_count = len(self.blackboard.scanned_ids)
            if scanned_count == self.scout.node_count or scanned_count % 4 == 0:
                self._event_llm_pending = True
            self._emit(
                "scan.completed",
                budget,
                completed_budget,
                {"blackboard": self.blackboard.snapshot()},
            )
        return 0

    def _choose_public_scan(self, budget: float) -> Action | None:
        """Ask the injected commander to select a legal public scan target."""
        unknown = [node_id for node_id in range(1, self.node_count + 1)
                   if self.blackboard.can_scan(node_id)]
        if not unknown:
            return None
        incident = {node_id: 0 for node_id in unknown}
        for left, right in self.blackboard.edges:
            if left in incident:
                incident[left] += 1
            if right in incident:
                incident[right] += 1
        shortlist = sorted(unknown, key=lambda node_id: (-incident[node_id], node_id))[:4]
        candidates = [
            Candidate(
                f"scan:{node_id}", Action("scan", node_id), 0,
                float(incident[node_id] + 1), float(incident[node_id] + 1) / 0.5,
                f"public frontier links {incident[node_id]}",
                (f"scan:{node_id}",),
            )
            for node_id in shortlist
        ]
        analysis = GraphAnalysis(build_graph(self.blackboard), {}, {}, 0)
        payload = self.commander.preview_payload(
            candidates, budget, analysis, self.blackboard.state_version
        ) if self.commander.can_request_llm else None
        if payload is not None:
            payload["stage"] = ControllerState.SCAN_ALL.value
        before = self.commander.llm_calls
        plan = self.commander.plan(
            candidates=candidates, budget=budget, analysis=analysis,
            request_payload=payload, state_version=self.blackboard.state_version,
        )
        self.blackboard.llm_attempts += self.commander.llm_calls - before
        if self.commander.llm_calls > before:
            if plan.source == "llm":
                self.llm_accepted += 1
            else:
                self.llm_fallbacks += 1
        selected_id = plan.candidate_ids[0] if plan.candidate_ids else candidates[0].candidate_id
        selected = next(
            (candidate.action for candidate in candidates if candidate.candidate_id == selected_id),
            candidates[0].action,
        )
        return selected if is_legal_action(selected, self.blackboard, budget) else None

    def _execute_next(self, budget: float) -> int:
        if self.cmg_candidate is not None:
            return self._execute_cmg(budget)
        if not self.queue:
            self._transition(ControllerState.REANALYZE, "queue_depleted", budget)
            return 0

        candidate_id = self.queue.pop(0)
        candidate = self.candidates.get(candidate_id)
        if candidate is None or candidate_id in self.failed_actions or candidate.action in self.failed_actions:
            self.consecutive_invalid += 1
            self._emit(
                "queue.revalidated",
                budget,
                budget,
                {
                    "source": "execute",
                    "enqueued_candidate_ids": list(self.queue),
                    "discarded": [{"candidate_id": candidate_id, "reason": "failed_or_unknown"}],
                },
            )
            self._transition(ControllerState.REANALYZE, "candidate_unavailable", budget)
            return 0
        if not is_legal_action(candidate.action, self.blackboard, budget):
            self.consecutive_invalid += 1
            self._emit(
                "queue.revalidated",
                budget,
                budget,
                {
                    "source": "execute",
                    "enqueued_candidate_ids": list(self.queue),
                    "discarded": [{"candidate_id": candidate_id, "reason": "illegal_action"}],
                },
            )
            self._transition(ControllerState.REANALYZE, "candidate_illegal", budget)
            return 0

        success = self._attempt_action(candidate.action, candidate_id, budget)
        if success:
            if self.config.llm_schedule is LLMSchedule.EVENT:
                self._event_llm_pending = True
            self.consecutive_invalid = 0
        else:
            self.failed_actions.add(candidate_id)
            self.failed_actions.add(candidate.action)
            self.consecutive_invalid += 1
        self._transition(
            ControllerState.REANALYZE,
            "action_succeeded" if success else "action_failed",
            self._last_trace_budget_after
            if self._last_trace_budget_after is not None
            else budget,
        )
        return 0

    @property
    def _cmg_enabled(self) -> bool:
        return (
            self.policy_mode is PolicyMode.V1_CMG
            and self.cmg_fallback_reason is None
            and self.calibration_profile.verified
        )

    def _fallback_to_v0(self, reason: str, budget: float) -> None:
        """Sticky, state-preserving escape hatch: never try CMG again this session."""
        if self.cmg_fallback_reason is None:
            self.cmg_fallback_reason = reason
            self._emit(
                "cmg.fallback",
                budget,
                budget,
                {"reason": reason, "profile_hash": self.calibration_profile.profile_hash or None},
            )
        self.cmg_candidate = None
        # Candidate generation may have happened before the failed CMG action.
        # Rebuild it so P0 exclusivity no longer hides lower-priority V0 work.
        self._transition(ControllerState.ANALYZE, "cmg_fallback", budget)

    def _plan_cmg(self, budget: float) -> int | None:
        """Plan exactly one action from a copied public state, without I/O."""
        try:
            candidate = choose_cmg_action(
                self.blackboard,
                self.response_ledger,
                self.calibration_profile,
                budget,
                cut_limit=self.config.cmg_cut_limit,
                iterations=self.config.cmg_iteration_limit,
                threshold=self.config.cmg_convergence_threshold,
                planning_seconds=self.config.cmg_planning_seconds,
            )
        except CMGPlanningError as exc:
            self._fallback_to_v0(str(exc), budget)
            return None
        if candidate is None:
            self._stop(StopReason.NO_POSITIVE_GAIN, budget)
            return None
        self.cmg_candidate = candidate
        self._last_step_selected_ids = [candidate.candidate_id]
        self._emit(
            "cmg.planned",
            budget,
            budget,
            self._cmg_trace_data(candidate),
        )
        self._transition(ControllerState.EXECUTE, "positive_cmg_action", budget)
        return None

    def _execute_cmg(self, budget: float) -> int:
        candidate = self.cmg_candidate
        if candidate is None or not is_legal_action(candidate.action, self.blackboard, budget):
            self._fallback_to_v0("illegal_hypothesis", budget)
            return 0
        success = self._attempt_action(candidate.action, candidate.candidate_id, budget)
        if not success:
            self.failed_actions.add(candidate.candidate_id)
            self.failed_actions.add(candidate.action)
            self._fallback_to_v0("action_rejected", self._last_trace_budget_after or budget)
            return 0
        self.cmg_candidate = None
        next_budget = self._last_trace_budget_after if self._last_trace_budget_after is not None else budget
        self._transition(ControllerState.ANALYZE, "cmg_action_succeeded" if success else "cmg_action_failed", next_budget)
        return 0

    def _attempt_action(self, action: Action, candidate_id: str, budget: float) -> bool:
        self.last_action_attempted = True
        self.action_attempts += 1
        self._last_step_action = asdict(action)
        before_w = (
            self.blackboard.nodes[action.target_node_1].w
            if action.kind == "comm" and action.target_node_1 in self.blackboard.nodes
            else None
        )
        before_node = self.blackboard.nodes.get(action.target_node_1)
        before_persona = before_node.persona if before_node is not None else None
        before_comm_left = before_node.comm_left if before_node is not None else None
        before_snapshot = self.blackboard.snapshot() if self._trace.enabled else None
        self._emit(
            "action.requested",
            budget,
            budget,
            {"candidate_id": candidate_id, "action": asdict(action)},
        )
        try:
            self.blackboard.env_calls += 1
            outcome = apply_action_outcome(self.env, self.blackboard, action, budget)
        except Exception as exc:
            self.last_action_succeeded = False
            self.last_action_error = type(exc).__name__
            self.action_failures += 1
            self._last_step_action_result = "exception"
            budget_after = self._trace_budget_after(budget)
            self._emit(
                "action.failed",
                budget,
                budget_after,
                {
                    "candidate_id": candidate_id,
                    "action": asdict(action),
                    "error": safe_error(exc),
                    "blackboard": self.blackboard.snapshot(),
                },
            )
            return False

        try:
            self.blackboard.set_budget(self._current_budget())
        except Exception:
            # Do not manufacture a debit after an ambiguous response.  The
            # controller will stop naturally once no action can be validated.
            self.blackboard.unresolved_nodes.add(action.target_node_1)
        self.last_action_succeeded = outcome.succeeded
        budget_after = self._trace_budget_after(budget)
        if outcome.succeeded:
            if action.kind == "comm":
                node = self.blackboard.nodes.get(action.target_node_1)
                if isinstance(before_w, (int, float)) and node is not None:
                    self.response_estimates.setdefault(
                        action.target_node_1, max(0.0, node.w - float(before_w))
                    )
                    if before_persona is not None and before_comm_left in (1, 2, 3):
                        self.response_ledger.record_success(
                            action.target_node_1,
                            float(before_w),
                            node.w,
                            persona=before_persona,
                            prompt_id=action.prompt_id or 1,
                            turn=4 - before_comm_left,
                        )
            self.action_successes += 1
            self._last_step_action_result = "success"
            self._emit(
                "action.completed",
                budget,
                budget_after,
                self._action_trace_data(candidate_id, outcome, before_snapshot),
            )
            return True

        self.action_failures += 1
        self._last_step_action_result = "failed"
        self._emit(
            "action.failed",
            budget,
            budget_after,
            self._action_trace_data(candidate_id, outcome, before_snapshot),
        )
        return False

    @staticmethod
    def _cmg_trace_data(candidate: ScoredCandidate) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "action": asdict(candidate.action),
            "score_before": candidate.score_before,
            "score_after": candidate.score_after,
            "gain": candidate.gain,
            "sigma": candidate.sigma,
            "lcb_roi": candidate.lcb_roi,
            "predicted_response_delta": candidate.response_delta,
        }

    @staticmethod
    def _plan_trace_data(plan: PlanCandidate) -> dict[str, Any]:
        return {
            "candidate_id": plan.candidate_id,
            "actions": [_action_name(action) for action in plan.actions],
            "first_action": _action_name(plan.first_action),
            "cost": plan.cost,
            "steps": plan.steps,
            "predicted_final_score": plan.predicted_final_score,
            "gain": plan.gain,
            "risk": plan.risk,
            "conservative_gain": plan.conservative_gain,
            "topology": plan.topology_summary,
            "evidence_ids": list(plan.evidence_ids),
        }

    def _action_trace_data(
        self,
        candidate_id: str,
        outcome: ActionOutcome,
        before_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "candidate_id": candidate_id,
            "action": asdict(outcome.action),
            "raw_response": outcome.raw_response,
            "success": outcome.succeeded,
            "rejected_reason": outcome.rejected_reason,
        }
        if before_snapshot is not None:
            data["blackboard_delta"] = self._blackboard_delta(
                before_snapshot, self.blackboard.snapshot()
            )
        return data

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        requested_mode = self.policy_mode
        if requested_mode is PolicyMode.B5_ADAPTIVE:
            requested_mode = PolicyMode.B4_BEAM_STRUCTURE

        if requested_mode in {PolicyMode.B3_SINGLE_STRUCTURE, PolicyMode.B4_BEAM_STRUCTURE}:
            # B3/B4 are opt-in and require all three action residuals, a
            # settlement model, and held-out influence evidence.  Otherwise
            # the same session transparently returns to the simpler baseline.
            if not self.calibration_profile.structure_eligible:
                self.effective_policy_mode = (
                    PolicyMode.B2_INFLUENCE
                    if self.calibration_profile.b2_eligible
                    else PolicyMode.B1_PERSUASION
                )
            else:
                self.effective_policy_mode = requested_mode
        else:
            self.effective_policy_mode = requested_mode

        if self.effective_policy_mode in {PolicyMode.B1_PERSUASION, PolicyMode.B2_INFLUENCE}:
            # P0 remains unverified by default. B2 is impossible without a
            # frozen influence archive and therefore transparently becomes B1.
            use_influence = self.effective_policy_mode is PolicyMode.B2_INFLUENCE and self.calibration_profile.b2_eligible
            candidates = persuasion_candidates(
                self.blackboard,
                budget,
                self.response_estimates,
                self.calibration_profile,
                use_influence=use_influence,
                failed_actions=self.failed_actions,
                ledger=self.response_ledger,
            )
            self.analysis = None
            self.candidates = {candidate.candidate_id: candidate for candidate in candidates}
            self._emit(
                "candidates.generated",
                budget,
                budget,
                {
                    "phase": phase,
                    "mode": "b2" if use_influence else "b1",
                    "filtered_count": len(candidates),
                    "candidates": [self._candidate_trace_data(candidate) for candidate in candidates],
                },
            )
            return
        self.analysis = self.analyst.analyze(self.blackboard)

        if self.effective_policy_mode is PolicyMode.PUBLIC_GREEDY:
            # In an overwhelmingly positive public graph, retain B1's
            # already-tested response pooling.  On mixed/risky graphs, the
            # experiment keeps a population prior for each untried target so
            # one noisy observation cannot steer every remaining target.
            public_response_fn = _response if public_positive_graph_gate_closed(self.blackboard) else public_response
            planner = ExperimentalPublicGreedyPlanner(
                lambda node_id, node, turn: public_response_fn(
                    node_id,
                    node.persona,
                    turn,
                    self.response_estimates,
                    self.calibration_profile,
                    self.response_ledger,
                ),
                candidate_limit=max(24, self.config.structure_candidate_limit),
                # Structure gains are directly recomputable from public
                # scans; do not spend four profitable responses probing a
                # node before allowing a clearly positive shield.
                min_observed_responses=0,
                structure_roi_margin=1.0,
                defer_comm_if_shieldable=self.config.enable_public_comm_shield_guard,
            )
            candidates = planner.candidates(
                self.blackboard,
                budget,
                self.failed_actions,
                observed_response_count=len(self.response_estimates),
            )
            self.structural_planner = None
            self.structural_plans = {}
            self.candidates = {candidate.candidate_id: candidate for candidate in candidates}
            self._emit(
                "candidates.generated",
                budget,
                budget,
                {
                    "phase": phase,
                    "mode": self.effective_policy_mode.value,
                    "filtered_count": len(candidates),
                    "candidates": [self._candidate_trace_data(candidate) for candidate in candidates],
                },
            )
            return

        if self.effective_policy_mode in {PolicyMode.B3_SINGLE_STRUCTURE, PolicyMode.B4_BEAM_STRUCTURE}:
            if self.config.llm_schedule is LLMSchedule.EVENT:
                self._event_llm_pending = True
            self.structural_planner = StructuralPlanner(
                self.calibration_profile,
                ledger=self.response_ledger,
                depth=self.config.structure_depth,
                width=self.config.structure_width,
                candidate_limit=self.config.structure_candidate_limit,
            )
            plans = self.structural_planner.plan_candidates(
                self.blackboard,
                budget,
                max(0, self._safe_step_limit - self._step_number),
                self.effective_policy_mode,
            )
            self.structural_plans = {plan.candidate_id: plan for plan in plans}
            self.candidates = {
                plan.candidate_id: Candidate(
                    plan.candidate_id,
                    plan.first_action,
                    0,
                    plan.gain,
                    max(0.0, plan.conservative_gain) / max(plan.cost, 0.5),
                    "complete structural plan " + ",".join(_action_name(item) for item in plan.actions),
                    plan.evidence_ids,
                )
                for plan in plans
                if plan.first_action is not None
                and plan.candidate_id not in self.failed_actions
                and plan.first_action not in self.failed_actions
                and is_legal_action(plan.first_action, self.blackboard, budget)
            }
            self._emit(
                "structural.planned",
                budget,
                budget,
                {
                    "phase": phase,
                    "mode": self.effective_policy_mode.value,
                    "eligible": self.calibration_profile.structure_eligible,
                    "plans": [self._plan_trace_data(plan) for plan in plans],
                },
            )
            candidates = list(self.candidates.values())
            self._emit(
                "candidates.generated", budget, budget,
                {"phase": phase, "mode": self.effective_policy_mode.value,
                 "filtered_count": len(candidates),
                 "candidates": [self._candidate_trace_data(candidate) for candidate in candidates]},
            )
            return

        candidates = self.analyst.generate_candidates(
            self.analysis,
            self.blackboard,
            budget,
            self.failed_actions,
            self.config,
        )
        self.candidates = {candidate.candidate_id: candidate for candidate in candidates}
        self._emit(
            "analysis.completed",
            budget,
            budget,
            self._analysis_trace_data(self.analysis, phase),
        )
        self._emit(
            "candidates.generated",
            budget,
            budget,
            {
                "phase": phase,
                "filtered_count": len(candidates),
                "candidates": [self._candidate_trace_data(candidate) for candidate in candidates],
            },
        )

    def _llm_candidate_options(self, candidates: list[Candidate]) -> list[Candidate]:
        """Bound ordinary immediate-ROI choices; trial controllers may compare tails."""
        if self.effective_policy_mode is PolicyMode.PUBLIC_GREEDY and self.commander.can_request_llm:
            best_roi = max(candidate.roi for candidate in candidates)
            return [candidate for candidate in candidates if candidate.roi >= 0.98 * best_roi][:4]
        return candidates

    def _create_plan(self, budget: float) -> None:
        candidates = list(self.candidates.values())
        if self.effective_policy_mode in {PolicyMode.B1_PERSUASION, PolicyMode.B2_INFLUENCE}:
            # The max-heap is already Python-optimal.  The LLM may never alter
            # a non-tied allocation, so do not spend a call merely to restate it.
            validation = self._valid_queue([candidate.candidate_id for candidate in candidates[:1]], budget)
            self.queue = list(validation.candidate_ids)
            self._last_step_selected_ids = list(self.queue)
            self._emit_queue_revalidated("persuasion_heap", validation, budget)
            return
        assert self.analysis is not None
        candidates = self._llm_candidate_options(candidates)
        request_payload: Mapping[str, Any] | None = None
        if self.commander.can_request_llm and self.config.llm_schedule is not LLMSchedule.OFF and (
            self.config.llm_schedule is LLMSchedule.STEP or self._event_llm_pending
        ):
            request_payload = self.commander.preview_payload(
                candidates, budget, self.analysis, self.blackboard.state_version
            )
            self._emit(
                "llm.requested",
                budget,
                budget,
                {"payload": request_payload, "llm_call": self.commander.llm_calls + 1},
            )
        llm_before = self.commander.llm_calls
        plan = self.commander.plan(
            candidates=candidates,
            budget=budget,
            analysis=self.analysis,
            request_payload=request_payload,
            state_version=self.blackboard.state_version,
        )
        self.blackboard.llm_attempts += self.commander.llm_calls - llm_before
        if self.commander.llm_calls > llm_before:
            if plan.source == "llm":
                self.llm_accepted += 1
            else:
                self.llm_fallbacks += 1
        if request_payload is not None:
            self._event_llm_pending = False
        if plan.request_payload is not None and plan.error is None:
            self._emit(
                "llm.completed",
                budget,
                budget,
                {
                    "raw_output": plan.raw_response,
                    "parsed": {
                        "accepted": plan.source == "llm",
                        "candidate_ids": list(plan.parsed_candidate_ids),
                        "fallback_reason": plan.fallback_reason,
                    },
                    "llm_calls": self.commander.llm_calls,
                },
            )
        if plan.source != "llm" and (plan.request_payload is not None or plan.source == "quota_exhausted"):
            self._emit(
                "llm.failed",
                budget,
                budget,
                {
                    "source": plan.source,
                    "fallback_reason": plan.fallback_reason,
                    "error": plan.error,
                    "llm_calls": self.commander.llm_calls,
                },
            )
        requested_candidate_ids = plan.candidate_ids
        if self.effective_policy_mode in {
            PolicyMode.PUBLIC_GREEDY,
            PolicyMode.B3_SINGLE_STRUCTURE,
            PolicyMode.B4_BEAM_STRUCTURE,
        }:
            # A structural candidate represents a *complete alternative plan*,
            # not an independently composable batch item.  Execute only its
            # first public action, then discard the plan and replan from the
            # observed result.
            requested_candidate_ids = requested_candidate_ids[:1]
        validation = self._valid_queue(requested_candidate_ids, budget)
        self.queue = list(validation.candidate_ids)
        self._last_step_selected_ids = list(self.queue)
        self._emit(
            "plan.created",
            budget,
            budget,
            {
                "source": plan.source,
                "fallback_reason": plan.fallback_reason,
                "planned_candidate_ids": list(plan.candidate_ids),
                "selected_candidate_ids": list(self.queue),
                "llm_calls": self.commander.llm_calls,
            },
        )
        self._emit_queue_revalidated("plan", validation, budget)

    def _emit_queue_revalidated(
        self, source: str, validation: QueueValidation, budget: float
    ) -> None:
        self._emit(
            "queue.revalidated",
            budget,
            budget,
            {
                "source": source,
                "enqueued_candidate_ids": list(validation.candidate_ids),
                "discarded": list(validation.discarded),
            },
        )

    def _transition(self, state: ControllerState, reason: str, budget: float) -> None:
        if state is self.state:
            return
        previous = self.state
        self.state = state
        self._emit(
            "state.transition",
            budget,
            budget,
            {"old_state": previous.value, "new_state": state.value, "reason": reason},
        )

    def _stop(self, reason: StopReason, budget: float) -> None:
        if self.state is ControllerState.STOP:
            return
        self.stop_reason = reason
        self._transition(ControllerState.STOP, reason.value, budget)
        final_budget = self._trace_budget_after(budget)
        self._emit(
            "run.stopped",
            budget,
            final_budget,
            {
                "reason": reason.value,
                "blackboard": self.blackboard.snapshot(),
                "action_attempts": self.action_attempts,
                "action_successes": self.action_successes,
                "action_failures": self.action_failures,
                "remaining_budget": final_budget,
                "llm_calls": self.commander.llm_calls,
            },
        )

    def _complete_step(self, result: int, state_before: str, budget_before: float) -> int:
        budget_after = (
            self._last_trace_budget_after
            if self._last_trace_budget_after is not None
            else self._trace_budget_after(budget_before)
        )
        self._emit(
            "step.completed",
            budget_before,
            budget_after,
            {
                "state_before": state_before,
                "return_code": result,
                "action": self._last_step_action,
                "action_result": self._last_step_action_result,
                "action_attempts": self.action_attempts,
                "action_successes": self.action_successes,
                "action_failures": self.action_failures,
                "selected_candidate_ids": self._last_step_selected_ids,
            },
        )
        return result

    def _emit(
        self,
        event: str,
        budget_before: float | None,
        budget_after: float | None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        """Keep all controller records on the trace's best-effort boundary."""
        self._trace.emit(
            event,
            step=self._step_number,
            state=self.state.value,
            budget_before=budget_before,
            budget_after=budget_after,
            data=data,
        )

    def _current_budget(self) -> float:
        return float(self.env.get_remaining_budget())

    def _trace_budget_after(self, fallback: float) -> float:
        if not self._trace.enabled:
            return fallback
        try:
            budget = self._current_budget()
        except Exception:
            budget = fallback
        self._last_trace_budget_after = budget
        return budget

    @staticmethod
    def _candidate_trace_data(candidate: Candidate) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "action": asdict(candidate.action),
            "priority": candidate.priority,
            "score": candidate.score,
            "roi": candidate.roi,
            "reason": candidate.reason,
        }

    @staticmethod
    def _analysis_trace_data(analysis: GraphAnalysis, phase: str) -> dict[str, Any]:
        return {
            "phase": phase,
            "node_count": analysis.node_count,
            "edge_count": analysis.edge_count,
            "community_count": analysis.community_count,
            "node_metrics": {
                node_id: asdict(metrics) for node_id, metrics in sorted(analysis.node_metrics.items())
            },
            "edge_metrics": [
                {"edge": list(edge), **asdict(metrics)}
                for edge, metrics in sorted(analysis.edge_metrics.items())
            ],
        }

    @staticmethod
    def _blackboard_delta(
        before: Mapping[str, Any], after: Mapping[str, Any]
    ) -> dict[str, Any]:
        before_nodes = before.get("nodes", {})
        after_nodes = after.get("nodes", {})
        if not isinstance(before_nodes, Mapping) or not isinstance(after_nodes, Mapping):
            return {}
        before_edges = {tuple(edge) for edge in before.get("edges", [])}
        after_edges = {tuple(edge) for edge in after.get("edges", [])}
        before_dead = set(before.get("dead_nodes", []))
        after_dead = set(after.get("dead_nodes", []))
        common_nodes = set(before_nodes).intersection(after_nodes)
        return {
            "added_nodes": {
                node_id: after_nodes[node_id]
                for node_id in sorted(set(after_nodes).difference(before_nodes))
            },
            "removed_nodes": {
                node_id: before_nodes[node_id]
                for node_id in sorted(set(before_nodes).difference(after_nodes))
            },
            "updated_nodes": {
                node_id: {"before": before_nodes[node_id], "after": after_nodes[node_id]}
                for node_id in sorted(common_nodes)
                if before_nodes[node_id] != after_nodes[node_id]
            },
            "added_edges": [list(edge) for edge in sorted(after_edges.difference(before_edges))],
            "removed_edges": [list(edge) for edge in sorted(before_edges.difference(after_edges))],
            "added_dead_nodes": sorted(after_dead.difference(before_dead)),
            "removed_dead_nodes": sorted(before_dead.difference(after_dead)),
        }

    def _valid_queue(self, candidate_ids: Sequence[object], budget: float) -> QueueValidation:
        """Revalidate plan IDs against current facts, conflicts, and budget."""
        accepted: list[str] = []
        discarded: list[dict[str, str]] = []
        seen: set[str] = set()
        shielded_nodes: set[int] = set()
        cut_endpoints: set[int] = set()
        remaining = budget
        for raw_candidate_id in candidate_ids:
            if not isinstance(raw_candidate_id, str):
                discarded.append({"candidate_id": repr(raw_candidate_id), "reason": "invalid_id"})
                continue
            candidate_id = raw_candidate_id
            if len(accepted) >= MAX_BATCH_ACTIONS:
                discarded.append({"candidate_id": candidate_id, "reason": "batch_limit"})
                continue
            if candidate_id in seen:
                discarded.append({"candidate_id": candidate_id, "reason": "duplicate"})
                continue
            seen.add(candidate_id)
            candidate = self.candidates.get(candidate_id)
            if candidate is None:
                discarded.append({"candidate_id": candidate_id, "reason": "unknown_candidate"})
                continue
            if candidate_id in self.failed_actions:
                discarded.append({"candidate_id": candidate_id, "reason": "failed_action"})
                continue
            action = candidate.action
            if action in self.failed_actions:
                discarded.append({"candidate_id": candidate_id, "reason": "failed_action"})
                continue
            cost = action_cost(action)
            if cost > remaining:
                discarded.append({"candidate_id": candidate_id, "reason": "insufficient_budget"})
                continue
            if not is_legal_action(action, self.blackboard, remaining):
                discarded.append({"candidate_id": candidate_id, "reason": "illegal_action"})
                continue
            if action.kind == "shield":
                if action.target_node_1 in cut_endpoints:
                    discarded.append({"candidate_id": candidate_id, "reason": "conflict"})
                    continue
                shielded_nodes.add(action.target_node_1)
            elif action.kind == "cut":
                assert action.target_node_2 is not None
                if action.target_node_1 in shielded_nodes or action.target_node_2 in shielded_nodes:
                    discarded.append({"candidate_id": candidate_id, "reason": "conflict"})
                    continue
                cut_endpoints.update((action.target_node_1, action.target_node_2))
            accepted.append(candidate_id)
            remaining -= cost
        return QueueValidation(tuple(accepted), tuple(discarded))


__all__ = [
    "BatchCommander",
    "BatchPlan",
    "ControllerState",
    "DeterministicScout",
    "GraphAnalyst",
    "MAX_LLM_CALLS",
    "QueueValidation",
    "RuntimeController",
    "StopReason",
    "infer_node_count",
]

# End inline: src/starnet/runtime/controller.py

# Begin inline: src/starnet/runtime/p8_controller.py
"""Shared P8 executor; production activation is controlled by qualification."""




class P8RuntimeController(RuntimeController):
    """Keep the full production executor and quota guards in a local trial."""

    def __init__(self, *args, p8_mode="audited", require_stage_envelope=False, **kwargs):
        if p8_mode not in ("conservative", "audited"):
            raise ValueError("unsupported P8 trial mode")
        super().__init__(*args, **kwargs)
        self.require_stage_envelope = require_stage_envelope
        self.p8_mode = p8_mode if (not require_stage_envelope or (
            self.node_count == 50 and self.initial_budget == 100.0
        )) else None
        self.p8_salt = None
        self.p8_cache = {}
        self.p8_options = False
        self.p8_proposals = 0
        self.p8_planning_errors = 0
        # Bounded, public-state-only diagnostics. A completed score alone does
        # not establish that the experimental planner actually ran.
        self.p8_refresh_reasons = {}
        self.p8_last_planning_error = None
        self.p8_selected_proposals = 0
        self.p8_selected_baseline = 0

    def _p8_reason(self, reason):
        self.p8_refresh_reasons[reason] = self.p8_refresh_reasons.get(reason, 0) + 1

    def _refresh_candidates(self, budget: float, phase: str) -> None:
        super()._refresh_candidates(budget, phase)
        self.p8_options = False
        for blocked, reason in (
            (self.p8_mode is None, "stage_envelope"),
            (self.require_stage_envelope and bool(self.blackboard.nonexistent_ids), "nonexistent_nodes"),
            (self.effective_policy_mode is not PolicyMode.PUBLIC_GREEDY, "policy_mode"),
            (len(self.blackboard.scanned_ids) != self.node_count, "incomplete_scan"),
            (not self.candidates, "no_candidates"),
        ):
            if blocked:
                self._p8_reason(reason)
                return
        try:
            if self.p8_salt is None:
                self.p8_salt = public_board_salt(self.blackboard)
            decision = choose_p8_action(
                self.blackboard, budget, self.response_estimates,
                remaining_steps=max(0, self._safe_step_limit - self.action_attempts),
                salt=self.p8_salt, mode=self.p8_mode, evaluation_cache=self.p8_cache,
            )
        except Exception as exc:
            self.p8_planning_errors += 1
            # Store the class only: arbitrary exception text can contain
            # injected environment or transport data.
            self.p8_last_planning_error = type(exc).__name__
            self._p8_reason("planning_error")
            return
        if not decision.deviated:
            self._p8_reason("baseline_selected")
            return
        action = decision.action
        if action in self.failed_actions or not is_legal_action(action, self.blackboard, budget):
            self._p8_reason("illegal_or_failed_proposal")
            return
        baseline = next((candidate for candidate in self.candidates.values()
                         if candidate.action == decision.baseline_action), None)
        if baseline is None:
            self._p8_reason("baseline_missing")
            return
        identity = f"p8:{action.kind}:{action.target_node_1}:{action.target_node_2}:{self.blackboard.state_version}"
        gain = (min(decision.mean_delta, decision.audit_mean_delta)
                if self.p8_mode == "audited" else decision.mean_delta)
        # Values are continuation advantages relative to the baseline plan,
        # not immediate changes to the environment's score.
        proposed = Candidate(identity, action, 0, gain, gain / action_cost(action),
                             f"P8 assumed-response continuation advantage; selection mean={decision.mean_delta:.6f}; "
                             f"selection minimum={decision.minimum_delta:.6f}; mode={self.p8_mode}; "
                             f"additional audit scenarios={len(decision.audit_paired_deltas)}, audit mean={decision.audit_mean_delta:.6f}, minimum={decision.audit_minimum_delta:.6f}; "
                             "baseline alternative has relative advantage zero", (identity,))
        fallback = Candidate(baseline.candidate_id, baseline.action, 0, 0.0, 0.0,
                             "Current public_greedy baseline; relative continuation advantage zero",
                             baseline.evidence_ids)
        self.candidates = {proposed.candidate_id: proposed, fallback.candidate_id: fallback}
        self.p8_options = True
        self.p8_proposals += 1
        self._p8_reason("proposal_exposed")

    def _llm_candidate_options(self, candidates):
        return candidates if self.p8_options else super()._llm_candidate_options(candidates)

    def _create_plan(self, budget):
        super()._create_plan(budget)
        if self.p8_options and self.queue:
            if self.queue[0].startswith("p8:"):
                self.p8_selected_proposals += 1
            else:
                self.p8_selected_baseline += 1


__all__ = ["P8RuntimeController"]

# End inline: src/starnet/runtime/p8_controller.py

# Begin inline: src/starnet/submission/starnet_model.py
"""赛方入口：保留 CaseVO 编排，把策略计算委托给可测试的纯 Python 控制器。"""


import json
import importlib as _starnet_importlib
from pathlib import Path
from typing import Any

import networkx as nx

# starnet-framework-compat-v2
try:
    _starnet_runtime = _starnet_importlib.import_module("case" + "vo")
    _starnet_framework = "documented"
except ModuleNotFoundError as _starnet_framework_error:
    if _starnet_framework_error.name != "case" + "vo":
        raise
    # The originally published Starter Kit used this legacy runtime name.
    _starnet_runtime = _starnet_importlib.import_module("agent_" + "mesa")
    _starnet_framework = "legacy"
AgentBase = _starnet_runtime.AgentBase
ModelBase = _starnet_runtime.ModelBase



def _runtime_config_for_descriptions(
    descriptions: list[dict[str, Any]], commander_description: dict[str, Any],
) -> PolicyConfig:
    """Build the sole runtime policy configuration from public persona data."""
    experimental_mode = next(
        (
            description.get("experimental_policy_mode")
            for description in descriptions
            if isinstance(description, dict) and description.get("experimental_policy_mode")
        ),
        None,
    )
    if experimental_mode != PolicyMode.PUBLIC_GREEDY.value:
        return DEFAULT_POLICY_CONFIG
    return PolicyConfig(
        enable_shield=True,
        enable_cut=True,
        enable_communicate=True,
        p0_exclusive=False,
        # One bounded model choice for each scan and intervention.  A 50/100-
        # node session needs at most 87/175 ordinary choices; the controller
        # also enforces the stage cap.
        max_llm_calls=240,
        policy_mode=PolicyMode.PUBLIC_GREEDY,
        # A platform trial must opt in from the one agent that owns the final
        # decision.  Flags on unrelated descriptions cannot alter the policy.
        enable_public_comm_shield_guard=(
            commander_description.get("experimental_public_comm_shield_guard") is True
        ),
    )


class CommanderAgent(AgentBase):
    """One direct CaseVO Prompt call; never uses ThoughtChain retries."""

    def __init__(self, unique_id: int, model: ModelBase, description: dict[str, Any]) -> None:
        super().__init__(unique_id, model, description, None)
        self._prompt = self.model.prompt_factory.get_template("commander_react.txt")

    def rank_candidates(self, payload: dict[str, Any]) -> object:
        """Return one strict decision object or raise for deterministic fallback."""
        raw = self._prompt.send_prompt(payload, agent=self, model=self.model)
        if not isinstance(raw, str):
            raise ValueError("commander response must be text")
        decision = json.loads(raw)
        required = {"state_version", "mode", "candidate_id", "reason_code", "evidence_ids"}
        if not isinstance(decision, dict) or set(decision) != required:
            raise ValueError("commander response schema mismatch")
        if decision["state_version"] != payload.get("state_version"):
            raise ValueError("stale commander state_version")
        if decision["candidate_id"] not in set(payload.get("candidate_ids", [])):
            raise ValueError("commander selected an illegal candidate")
        if not isinstance(decision["evidence_ids"], list):
            raise ValueError("commander evidence_ids must be a list")
        return decision

    def step(self) -> None:
        """The host model drives the role through ``rank_candidates``."""


class ParticipantSquadModel(ModelBase):
    """官方固定签名的模型入口。"""

    def __init__(self, host_env: object, person_list: list[dict[str, Any]], llm: object) -> None:
        # One CaseVO agent owns every final scan/intervention choice. Python
        # supplies analysis and validation without creating inactive agents.
        agent_graph = nx.Graph()
        agent_graph.add_node(0)
        prompt_path = Path(__file__).resolve().parent / "prompt"
        if _starnet_framework == "documented":
            super().__init__(agent_graph, llm, prompt_path=str(prompt_path.resolve()), reflect_file="reflect.txt")
        else:
            # The legacy agent_mesa API from the published Starter Kit only
            # accepts the graph and injected LLM.
            super().__init__(agent_graph, llm)
        self.env = host_env

        descriptions = [item for item in person_list if isinstance(item, dict)]
        commander_description = next(
            (item for item in descriptions if item.get("role") == "CommanderAgent"),
            descriptions[-1] if descriptions else {"role": "CommanderAgent"},
        )
        self.commander_agent = CommanderAgent(0, self, commander_description)
        self.add_agent(self.commander_agent, 0)

        runtime_config = _runtime_config_for_descriptions(descriptions, commander_description)

        p8_mode = qualified_p8_mode(commander_description.get("experimental_p8_mode"))
        controller_type = P8RuntimeController if p8_mode is not None else RuntimeController
        controller_options = {"p8_mode": p8_mode, "require_stage_envelope": True} if p8_mode is not None else {}
        self.controller = controller_type(
            host_env,
            llm_ranker=self.commander_agent.rank_candidates,
            stage=ContestStage.PRELIMINARY,
            config=runtime_config,
            **controller_options,
        )

    def step(self) -> int:
        result = self.controller.step()
        if self.controller.last_action_attempted:
            self.schedule.time += 1
        return result

# End inline: src/starnet/submission/starnet_model.py

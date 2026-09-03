"""确定性扫描、图分析和批次执行的纯 Python 运行时控制器。

这个模块不依赖 ``agent_mesa``。提交入口可以把 CaseVO 的 Commander 链包装成
``llm_ranker`` 回调，再把 ``RuntimeController.step()`` 的返回值直接作为模型
``step()`` 的状态码使用。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from starnet.model.blackboard import Blackboard
from starnet.policy.actions import Action, action_cost, is_legal_action
from starnet.policy.candidates import (
    Candidate,
    generate_candidates,
    parse_llm_batch,
    select_deterministic_batch,
)
from starnet.policy.graph_analysis import GraphAnalysis, analyze_graph
from starnet.runtime.env_adapter import StarNetEnvironment, apply_action


MAX_LLM_CALLS = 3
MAX_BATCH_ACTIONS = 10
MAX_CONSECUTIVE_INVALID = 3


class ControllerState(str, Enum):
    """控制器的显式状态，便于模拟环境和提交入口观测。"""

    INIT = "INIT"
    SCAN_ALL = "SCAN_ALL"
    ANALYZE = "ANALYZE"
    PLAN_BATCH = "PLAN_BATCH"
    EXECUTE = "EXECUTE"
    REANALYZE = "REANALYZE"
    STOP = "STOP"


def infer_node_count(initial_budget: float) -> int:
    """从公开初始预算推断当前赛制规模。"""
    return 100 if initial_budget >= 150.0 else 50


class DeterministicScout:
    """按固定 ID 顺序扫描，完全不调用 LLM。"""

    def __init__(self, node_count: int) -> None:
        if node_count <= 0:
            raise ValueError("node_count 必须为正整数")
        self.node_count = node_count
        self._next_node_id = 1

    @property
    def exhausted(self) -> bool:
        return self._next_node_id > self.node_count

    def next_action(self, blackboard: Blackboard) -> Action | None:
        """返回下一个未知 ID 的 scan 动作；已知 ID 不会重复请求环境。"""
        while self._next_node_id <= self.node_count:
            node_id = self._next_node_id
            self._next_node_id += 1
            if blackboard.can_scan(node_id):
                return Action("scan", node_id)
        return None


class GraphAnalyst:
    """图分析模块的轻量角色包装，保留单文件提交时的清晰职责边界。"""

    def analyze(self, blackboard: Blackboard) -> GraphAnalysis:
        return analyze_graph(blackboard)

    def generate_candidates(
        self,
        analysis: GraphAnalysis,
        blackboard: Blackboard,
        budget: float,
        failed_actions: set[str],
    ) -> list[Candidate]:
        return generate_candidates(analysis, blackboard, budget, failed_actions)


LlmRanker = Callable[[dict[str, Any]], object]


@dataclass(frozen=True)
class BatchPlan:
    """一次仲裁后的候选 ID 队列及其来源。"""

    candidate_ids: tuple[str, ...]
    used_llm: bool


class BatchCommander:
    """负责 LLM 候选排序、调用配额和确定性回退。"""

    def __init__(self, llm_ranker: LlmRanker | None = None) -> None:
        self.llm_ranker = llm_ranker
        self.llm_calls = 0

    def plan(
        self,
        *,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
    ) -> BatchPlan:
        """返回 LLM 排序或确定性排序，LLM 故障不会传播到评测循环。"""
        candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
        selected_ids: list[str] = []
        used_llm = False

        if self.llm_ranker is not None and self.llm_calls < MAX_LLM_CALLS and candidate_map:
            # 计数在请求前递增，因此超时和异常也会消耗本次额度。
            self.llm_calls += 1
            try:
                payload = self._build_payload(candidates, budget, analysis)
                parsed = parse_llm_batch(self.llm_ranker(payload), candidate_map, budget)
                selected_ids = list(parsed or [])
                used_llm = bool(selected_ids)
            except Exception:
                selected_ids = []

        if not selected_ids:
            selected_ids = list(select_deterministic_batch(candidates, budget, MAX_BATCH_ACTIONS))

        return BatchPlan(tuple(selected_ids), used_llm)

    def _build_payload(
        self,
        candidates: Sequence[Candidate],
        budget: float,
        analysis: GraphAnalysis,
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
            "budget": budget,
            "llm_calls": self.llm_calls,
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
                    "roi": candidate.roi,
                    "reason": candidate.reason,
                }
                for candidate in candidates
            ],
        }


class RuntimeController:
    """每次 ``step`` 最多执行一次公开环境调用的 V0 状态机。

    ``step`` 返回 ``0`` 表示应继续调度，返回 ``1`` 表示停止。调用方若维护
    ``schedule.time``，仅应在 ``last_action_attempted`` 为真时递增一次。
    """

    def __init__(
        self,
        env: StarNetEnvironment,
        llm_ranker: LlmRanker | None = None,
        *,
        initial_budget: float | None = None,
        node_count: int | None = None,
        blackboard: Blackboard | None = None,
    ) -> None:
        self.env = env
        self.blackboard = blackboard if blackboard is not None else Blackboard()
        self.initial_budget = float(
            env.get_remaining_budget() if initial_budget is None else initial_budget
        )
        self.node_count = infer_node_count(self.initial_budget) if node_count is None else node_count
        self.scout = DeterministicScout(self.node_count)
        self.analyst = GraphAnalyst()
        self.commander = BatchCommander(llm_ranker)
        self.state = ControllerState.INIT
        self.analysis: GraphAnalysis | None = None
        self.candidates: dict[str, Candidate] = {}
        self.queue: list[str] = []
        self.failed_actions: set[str] = set()
        self.consecutive_invalid = 0
        self.last_action_attempted = False
        self.last_action_succeeded: bool | None = None

    @property
    def llm_calls(self) -> int:
        return self.commander.llm_calls

    @property
    def stopped(self) -> bool:
        return self.state is ControllerState.STOP

    def step(self) -> int:
        """推进状态机；本方法中任一路径至多调用一次环境 API。"""
        self.last_action_attempted = False
        self.last_action_succeeded = None

        # 状态转换不触发环境动作，可在同一个调度回合内继续直到需要执行动作。
        for _ in range(8):
            if self.state is ControllerState.STOP:
                return 1

            budget = float(self.env.get_remaining_budget())
            if self.state is ControllerState.INIT:
                self.state = ControllerState.SCAN_ALL
                continue

            if self.state is ControllerState.SCAN_ALL:
                return self._scan_next(budget)

            if self.state is ControllerState.ANALYZE:
                self._refresh_candidates(budget)
                self.state = ControllerState.PLAN_BATCH if self.candidates else ControllerState.STOP
                continue

            if self.state is ControllerState.PLAN_BATCH:
                if self.analysis is None or not self.candidates:
                    self.state = ControllerState.STOP
                    continue
                plan = self.commander.plan(
                    candidates=list(self.candidates.values()),
                    budget=budget,
                    analysis=self.analysis,
                )
                self.queue = self._valid_queue(plan.candidate_ids, budget)
                self.state = ControllerState.EXECUTE if self.queue else ControllerState.STOP
                continue

            if self.state is ControllerState.EXECUTE:
                return self._execute_next(budget)

            if self.state is ControllerState.REANALYZE:
                self._refresh_candidates(budget)
                previous_queue = self.queue
                self.queue = self._valid_queue(previous_queue, budget)
                invalidated = len(previous_queue) - len(self.queue)
                if invalidated:
                    self.consecutive_invalid += invalidated
                # 状态变化使过半队列失效时，旧批次已不再代表当前图，重新仲裁。
                if previous_queue and invalidated * 2 > len(previous_queue):
                    self.queue.clear()
                if self.consecutive_invalid >= MAX_CONSECUTIVE_INVALID:
                    self.queue.clear()
                    self.consecutive_invalid = 0
                if self.queue:
                    self.state = ControllerState.EXECUTE
                elif self.candidates:
                    self.state = ControllerState.PLAN_BATCH
                else:
                    self.state = ControllerState.STOP
                continue

        # 防止未来状态变更产生无界的无动作循环。
        self.state = ControllerState.STOP
        return 1

    def _scan_next(self, budget: float) -> int:
        action = self.scout.next_action(self.blackboard)
        if action is None:
            self.state = ControllerState.ANALYZE
            return 0
        if not is_legal_action(action, self.blackboard, budget):
            # 预算不足时，剩余扫描不能凭空完成。
            self.state = ControllerState.STOP
            return 1

        self.last_action_attempted = True
        try:
            self.last_action_succeeded = apply_action(self.env, self.blackboard, action, budget)
        except Exception:
            self.last_action_succeeded = False
        if self.scout.exhausted:
            self.state = ControllerState.ANALYZE
        return 0

    def _execute_next(self, budget: float) -> int:
        if not self.queue:
            self.state = ControllerState.REANALYZE
            return 0

        candidate_id = self.queue.pop(0)
        candidate = self.candidates.get(candidate_id)
        if candidate is None or candidate_id in self.failed_actions:
            self.consecutive_invalid += 1
            self.state = ControllerState.REANALYZE
            return 0
        if not is_legal_action(candidate.action, self.blackboard, budget):
            self.consecutive_invalid += 1
            self.state = ControllerState.REANALYZE
            return 0

        self.last_action_attempted = True
        try:
            success = apply_action(self.env, self.blackboard, candidate.action, budget)
        except Exception:
            success = False
        self.last_action_succeeded = success
        if success:
            self.consecutive_invalid = 0
        else:
            self.failed_actions.add(candidate_id)
            self.consecutive_invalid += 1
        self.state = ControllerState.REANALYZE
        return 0

    def _refresh_candidates(self, budget: float) -> None:
        self.analysis = self.analyst.analyze(self.blackboard)
        candidates = self.analyst.generate_candidates(
            self.analysis,
            self.blackboard,
            budget,
            self.failed_actions,
        )
        self.candidates = {candidate.candidate_id: candidate for candidate in candidates}

    def _valid_queue(self, candidate_ids: Sequence[str], budget: float) -> list[str]:
        """再次校验 LLM/旧队列，过滤未知、失效、冲突和超预算动作。"""
        accepted: list[str] = []
        seen: set[str] = set()
        shielded_nodes: set[int] = set()
        cut_endpoints: set[int] = set()
        remaining = budget
        for candidate_id in candidate_ids:
            if len(accepted) >= MAX_BATCH_ACTIONS or candidate_id in seen:
                continue
            seen.add(candidate_id)
            candidate = self.candidates.get(candidate_id)
            if candidate is None or candidate_id in self.failed_actions:
                continue
            action = candidate.action
            cost = action_cost(action)
            if cost > remaining or not is_legal_action(action, self.blackboard, remaining):
                continue
            if action.kind == "shield":
                if action.target_node_1 in cut_endpoints:
                    continue
                shielded_nodes.add(action.target_node_1)
            elif action.kind == "cut":
                assert action.target_node_2 is not None
                if (
                    action.target_node_1 in shielded_nodes
                    or action.target_node_2 in shielded_nodes
                ):
                    continue
                cut_endpoints.update((action.target_node_1, action.target_node_2))
            accepted.append(candidate_id)
            remaining -= cost
        return accepted


__all__ = [
    "BatchCommander",
    "BatchPlan",
    "ControllerState",
    "DeterministicScout",
    "GraphAnalyst",
    "MAX_LLM_CALLS",
    "RuntimeController",
    "infer_node_count",
]

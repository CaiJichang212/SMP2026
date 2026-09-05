"""赛方入口：保留 CaseVO 编排，把策略计算委托给可测试的纯 Python 控制器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
from casevo import AgentBase, ModelBase

from starnet.runtime.controller import RuntimeController
from starnet.runtime.stage import ContestStage


class BaseStarAgent(AgentBase):
    """没有自主环境权限的角色基类，所有实际动作都由控制器再次校验。"""

    def step(self) -> None:
        return None


class ScoutAnalystAgent(BaseStarAgent):
    """Produces only Python-validated scan facts and candidate evidence."""


class CommanderAgent(BaseStarAgent):
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


class ExecutorAgent(BaseStarAgent):
    """The controller remains the final public-API and action validator."""


class ParticipantSquadModel(ModelBase):
    """官方固定签名的模型入口。"""

    def __init__(self, host_env: object, person_list: list[dict[str, Any]], llm: object) -> None:
        agent_graph = nx.Graph()
        agent_graph.add_nodes_from((0, 1, 2))
        agent_graph.add_edges_from(((0, 1), (1, 2)))
        prompt_path = Path(__file__).resolve().parent / "prompt"
        super().__init__(agent_graph, llm, prompt_path=str(prompt_path.resolve()), reflect_file="reflect.txt")
        self.env = host_env

        descriptions = list(person_list)
        while len(descriptions) < 3:
            descriptions.append({"role": "星网策略角色"})
        self.scout_agent = ScoutAnalystAgent(0, self, descriptions[0], None)
        self.commander_agent = CommanderAgent(2, self, descriptions[2])
        self.executor_agent = ExecutorAgent(1, self, descriptions[1], None)
        self.add_agent(self.scout_agent, 0)
        self.add_agent(self.executor_agent, 1)
        self.add_agent(self.commander_agent, 2)

        self.controller = RuntimeController(
            host_env,
            llm_ranker=self.commander_agent.rank_candidates,
            stage=ContestStage.PRELIMINARY,
        )

    def step(self) -> int:
        result = self.controller.step()
        if self.controller.last_action_attempted:
            self.schedule.time += 1
        return result

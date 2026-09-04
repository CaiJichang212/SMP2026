"""赛方入口：保留 CaseVO 编排，把策略计算委托给可测试的纯 Python 控制器。"""

from __future__ import annotations

import threading
from typing import Any

import networkx as nx
from casevo import AgentBase, JsonStep, ModelBase

from starnet.runtime.controller import RuntimeController


class BaseStarAgent(AgentBase):
    """没有自主环境权限的角色基类，所有实际动作都由控制器再次校验。"""

    def step(self) -> None:
        return None


class ScoutAgent(BaseStarAgent):
    """已注册的侦察角色；固定 ID 扫描由 DeterministicScout 完成。"""


class GraphAnalystAgent(BaseStarAgent):
    """已注册的图分析角色；NetworkX 计算在 Python 控制器中保持确定性。"""


class CommanderAgent(BaseStarAgent):
    """只允许 LLM 对 Python 生成的候选 ID 批次排序。"""

    def __init__(self, unique_id: int, model: ModelBase, description: dict[str, Any]) -> None:
        super().__init__(unique_id, model, description, None)
        self.setup_chain(
            {"rank": [JsonStep(0, self.model.prompt_factory.get_template("commander_react.txt"))]}
        )
        self._lock = threading.Lock()

    def rank_candidates(self, payload: dict[str, Any]) -> object:
        """返回 JsonStep 已解析的 JSON；异常交由控制器走确定性回退。"""
        with self._lock:
            self.chains["rank"].set_input(payload)
            self.chains["rank"].run_step()
            return self.chains["rank"].get_output().get("json")


class ParticipantSquadModel(ModelBase):
    """官方固定签名的模型入口。"""

    def __init__(self, host_env: object, person_list: list[dict[str, Any]], llm: object) -> None:
        agent_graph = nx.Graph()
        agent_graph.add_nodes_from((0, 1, 2))
        agent_graph.add_edges_from(((0, 1), (1, 2)))
        super().__init__(agent_graph, llm)
        self.env = host_env

        descriptions = list(person_list)
        while len(descriptions) < 3:
            descriptions.append({"role": "星网策略角色"})
        self.scout_agent = ScoutAgent(0, self, descriptions[0], None)
        self.analyst_agent = GraphAnalystAgent(1, self, descriptions[1], None)
        self.commander_agent = CommanderAgent(2, self, descriptions[2])
        self.add_agent(self.scout_agent, 0)
        self.add_agent(self.analyst_agent, 1)
        self.add_agent(self.commander_agent, 2)

        self.controller = RuntimeController(
            host_env,
            llm_ranker=self.commander_agent.rank_candidates,
        )

    def step(self) -> int:
        result = self.controller.step()
        if self.controller.last_action_attempted:
            self.schedule.time += 1
        return result

"""赛方入口：保留 CaseVO 编排，把策略计算委托给可测试的纯 Python 控制器。"""

from __future__ import annotations

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

from starnet.runtime.controller import RuntimeController
from starnet.runtime.stage import ContestStage
from starnet.policy.config import DEFAULT_POLICY_CONFIG, PolicyConfig, PolicyMode
from starnet.policy.p8_qualification import P8_CERTIFIED_MODE, qualified_p8_mode
from starnet.policy.p11_qualification import P11_CERTIFIED_MODE, qualified_p11_mode
from starnet.runtime.p8_controller import P8RuntimeController
from starnet.runtime.p11_prompt_controller_experiment import PromptLearningRuntimeController


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

        requested_p11 = commander_description.get(
            "experimental_p11_mode", P11_CERTIFIED_MODE,
        )
        p11_mode = qualified_p11_mode(requested_p11)
        certified_p8_mode = qualified_p8_mode(P8_CERTIFIED_MODE)
        if p11_mode is not None and certified_p8_mode is None:
            p11_mode = None
        if p11_mode is not None and runtime_config.policy_mode is not PolicyMode.PUBLIC_GREEDY:
            runtime_config = PolicyConfig(
                enable_shield=True, enable_cut=True, enable_communicate=True,
                p0_exclusive=False, max_llm_calls=240,
                policy_mode=PolicyMode.PUBLIC_GREEDY,
            )
        p8_mode = qualified_p8_mode(commander_description.get("experimental_p8_mode"))
        if p11_mode is not None:
            p8_mode = certified_p8_mode
            controller_type = PromptLearningRuntimeController
            controller_options = {
                "p8_mode": p8_mode,
                "require_stage_envelope": True,
                "max_probe_budget": 12.0,
                "max_probe_nodes": 2,
            }
        else:
            controller_type = P8RuntimeController if p8_mode is not None else RuntimeController
            controller_options = (
                {"p8_mode": p8_mode, "require_stage_envelope": True}
                if p8_mode is not None else {}
            )
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

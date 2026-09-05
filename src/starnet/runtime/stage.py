"""Explicit contest-stage contract.

The stage is deployment configuration, never an observation inferred from a
budget response or from the ids that happened to be scanned.  Keeping this in
one small module makes the resource envelope reviewable and testable.
"""

from __future__ import annotations

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

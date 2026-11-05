"""What gets run: the registered plan, read from ``eval/plan.yaml`` (§11.5).

The file is hashed into every record, so a result can always be traced to the plan it came from,
and a change after the freeze shows up as a different hash.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from tessera.evaluation.items import EvalItem, Level
from tessera.protocol.case import SystemCondition


class StabilityPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: Level = Level.MESSAGE
    temperature: float
    runs: dict[SystemCondition, int]
    #: Share of items that get stability runs. Lowered only by the fallback order in §11.5.
    share: float = 1.0


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    first: SystemCondition
    second: SystemCondition
    metric: Literal["false_reassurance", "macro_f1"]


class RunPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    primary: tuple[SystemCondition, ...]
    stability: StabilityPlan
    #: H1 and H2. They are tested alone, so they carry no correction.
    registered: tuple[Comparison, ...]
    #: H3 and H4. Holm-Bonferroni runs over this family.
    secondary: tuple[Comparison, ...]
    non_inferiority_margin: float


def load_plan(path: Path) -> RunPlan:
    return RunPlan.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def plan_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@dataclass(frozen=True)
class Job:
    """One system on one item, one time."""

    item: EvalItem
    condition: SystemCondition
    run: int = 0
    temperature: float | None = None

    @property
    def name(self) -> str:
        return f"{self.item.item_id}~{self.condition.value}~{self.run}"


def _in_share(index: int, share: float) -> bool:
    """A steady share of items, spread evenly through the list."""
    return int((index + 1) * share) > int(index * share)


def jobs_for(
    items: Sequence[EvalItem],
    plan: RunPlan,
    *,
    conditions: Sequence[SystemCondition] | None = None,
    stability: bool = True,
) -> list[Job]:
    """Item by item, so a run stopped part way still holds complete pairs to compare."""
    wanted = set(conditions) if conditions else None
    jobs: list[Job] = []
    for index, item in enumerate(items):
        jobs += [
            Job(item, condition)
            for condition in plan.primary
            if wanted is None or condition in wanted
        ]
        extra = plan.stability
        if not stability or item.level is not extra.level or not _in_share(index, extra.share):
            continue
        for condition, runs in extra.runs.items():
            if wanted is None or condition in wanted:
                jobs += [Job(item, condition, run, extra.temperature) for run in range(1, runs + 1)]
    return jobs

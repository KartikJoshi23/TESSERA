"""Findings: what an agent asserts, with the evidence it cites.

A finding keeps its ID across revisions. Each revision is a new version, and the earlier version is
kept in the blackboard's history, so the conversation can be replayed exactly.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from tessera.protocol.claims import Assertion
from tessera.protocol.common import AgentId, Confidence


class FindingStatus(StrEnum):
    ACTIVE = "active"
    CHALLENGED = "challenged"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str
    version: int = 1
    author: AgentId
    assertion: Assertion
    confidence: Confidence = "medium"
    evidence_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    status: FindingStatus = FindingStatus.ACTIVE
    rationale: str = ""
    round: int = 0
    #: Evidence IDs cited that no tool created in this case. Conflict type C6 reads this.
    unknown_evidence_ids: tuple[str, ...] = Field(default=())

    @property
    def is_live(self) -> bool:
        return self.status in (FindingStatus.ACTIVE, FindingStatus.CHALLENGED)

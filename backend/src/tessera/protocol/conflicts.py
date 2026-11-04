"""Conflicts between findings, and how the Reconciler resolved them (§6.6–§6.7)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConflictType(StrEnum):
    C1 = "C1"  # relevance
    C2 = "C2"  # identity
    C3 = "C3"  # scope
    C4 = "C4"  # contact
    C5 = "C5"  # alert versus register
    C6 = "C6"  # missing evidence
    C7 = "C7"  # claim versus record


class ConflictStatus(StrEnum):
    OPEN = "open"
    CHALLENGED = "challenged"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    #: The trigger no longer holds, for example because an agent revised its finding.
    SETTLED = "settled"


class Conflict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conflict_id: str
    type: ConflictType
    finding_ids: tuple[str, ...]
    #: Measured separately, to show what the model adds beyond the fixed rules.
    detected_by: Literal["detector", "REC"]
    status: ConflictStatus = ConflictStatus.OPEN
    summary: str = ""
    resolution_id: str | None = None


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution_id: str
    conflict_id: str
    outcome: Literal["upheld", "overturned", "merged", "unresolved"]
    winning_finding_ids: tuple[str, ...] = ()
    precedence_rule: str
    evidence_ids: tuple[str, ...] = ()
    rationale: str = ""
    round: int = 0

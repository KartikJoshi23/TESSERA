"""The case record, and the guarantee that gold labels never reach a system under test."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tessera.protocol.contacts import ContactPoint


class SystemCondition(StrEnum):
    """The experimental conditions (implementation-plan.md §10.2)."""

    CREW_FULL = "CREW-FULL"
    CREW_SHARE = "CREW-SHARE"
    CREW_SILO = "CREW-SILO"
    CREW_NV = "CREW-NV"
    SA_BASE = "SA-BASE"
    SA_VER = "SA-VER"
    SA_SC5 = "SA-SC5"
    SA_MAX = "SA-MAX"
    SA_LARGER = "SA-LARGER"
    RULES_ONLY = "RULES-ONLY"


class CaseRecord(BaseModel):
    """What the blackboard stores about a case. All text here is already masked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    condition: SystemCondition
    mode: str
    offer_text: str
    channel: str | None = None
    corpus_item_id: str | None = None
    synthetic: bool = True
    contact_points: tuple[ContactPoint, ...] = ()
    pii_warning_kinds: tuple[str, ...] = ()
    config: dict[str, Any] = Field(default_factory=dict)


def strip_gold(item: Mapping[str, Any]) -> dict[str, Any]:
    """Drop every ``gold_*`` field from a dataset item before a case is created."""
    return {key: value for key, value in item.items() if not key.startswith("gold")}

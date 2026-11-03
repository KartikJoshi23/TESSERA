"""Evidence records: the only things a claim may cite (ADR-0002).

Evidence is created only by deterministic tools through :func:`mint_evidence`.

* The ID is a content hash that includes the case ID, so an agent cannot invent or reuse one.
* Evidence from restricted sources stores only derived, non-identifying fields plus a reference
  to the restricted row. Identifying values stay in the restricted store.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceKind(StrEnum):
    REGISTER_ENTRY = "register_entry"
    NO_MATCH = "no_match"
    ALERT_ENTRY = "alert_entry"
    WARNING_ENTRY = "warning_entry"
    UNLICENSED_ENTRY = "unlicensed_entry"
    RULE_CARD = "rule_card"
    DERIVED_ANALYSIS = "derived_analysis"


#: Field names allowed in evidence from restricted sources: derived, non-identifying data only.
RESTRICTED_SAFE_FIELDS = frozenset(
    {
        "record_kind",
        "match_type",
        "matched_on",
        "score",
        "searched",
        "lookalike",
        "same_registrable",
        "edit_distance",
        "patterns",
        "equal_to_official",
        "beneficiary_matches",
        "wallet_requested",
        "iban_valid",
        "iban_country",
        "wallet_chain",
    }
)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str
    case_id: str
    source_id: str
    kind: EvidenceKind
    locator: str
    fields: dict[str, Any] = Field(default_factory=dict)
    snapshot_id: str | None = None
    snapshot_date: date | None = None
    restricted: bool = False
    restricted_ref: str | None = None
    display_link: str | None = None
    minted_by: str


def canonical_json(value: Any) -> str:
    """Stable JSON serialisation used for content hashing."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def mint_evidence(
    *,
    case_id: str,
    source_id: str,
    kind: EvidenceKind,
    locator: str,
    fields: dict[str, Any],
    minted_by: str,
    snapshot_id: str | None = None,
    snapshot_date: date | None = None,
    restricted: bool = False,
    restricted_ref: str | None = None,
    display_link: str | None = None,
) -> EvidenceRecord:
    """Create an evidence record. Only deterministic tools call this."""
    if restricted:
        unsafe = sorted(set(fields) - RESTRICTED_SAFE_FIELDS)
        if unsafe:
            raise ValueError(f"restricted evidence may hold derived fields only; got {unsafe}")
        if not restricted_ref:
            raise ValueError("restricted evidence needs a restricted_ref")
    payload = canonical_json(
        {
            "case": case_id,
            "source": source_id,
            "kind": kind.value,
            "locator": locator,
            "snapshot": snapshot_id,
            "fields": fields,
            "ref": restricted_ref,
        }
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return EvidenceRecord(
        evidence_id=f"E-{digest}",
        case_id=case_id,
        source_id=source_id,
        kind=kind,
        locator=locator,
        fields=fields,
        snapshot_id=snapshot_id,
        snapshot_date=snapshot_date,
        restricted=restricted,
        restricted_ref=restricted_ref,
        display_link=display_link,
        minted_by=minted_by,
    )


class ToolResult(BaseModel):
    """What a tool returns: evidence it minted plus a compact summary for the caller."""

    model_config = ConfigDict(frozen=True)

    tool: str
    evidence: tuple[EvidenceRecord, ...] = ()
    summary: dict[str, Any] = Field(default_factory=dict)
    #: True when ``summary`` holds restricted values. Such a summary must never be persisted
    #: raw, and must pass through the masking gateway before any model call.
    restricted: bool = False
    warnings: tuple[str, ...] = ()

"""What each agent must return.

These schemas are deliberately flatter than the internal claim catalogue: models get fewer ways to
go wrong, and each agent's code turns its output into typed findings. Unknown extra fields are
ignored, because they are harmless. Missing or malformed required fields trigger one repair.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tessera.protocol.claims import AlertAbout, ContactStatus, CoveredValue, LicenceStatusValue
from tessera.protocol.common import (
    AgentId,
    Confidence,
    Regulator,
    RelevanceStatus,
    ResultCode,
    Zone,
)
from tessera.protocol.conflicts import ConflictType
from tessera.protocol.messages import Objection


class _Output(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ResponseItem(_Output):
    """An answer to a message in the agent's inbox."""

    message_id: str
    action: Literal["REVISE", "REBUT", "CONCEDE", "ANSWER"]
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    #: For REVISE: only the fields of the challenged finding that change.
    revised_fields: dict[str, Any] | None = None


class OutgoingItem(_Output):
    """A message an agent wants to send. The protocol rules decide whether it goes out."""

    performative: Literal["REQUEST", "CHALLENGE"]
    to: AgentId
    question: str
    target_finding_id: str | None = None
    objection: Objection | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class _Conversational(_Output):
    responses: list[ResponseItem] = Field(default_factory=list)
    outgoing: list[OutgoingItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- Jurisdiction


class ActivityItem(_Output):
    code: str
    quote: str
    confidence: Confidence = "medium"


class ZoneItem(_Output):
    zone: Zone
    basis: Literal["address", "name", "domain", "phone", "claim", "other"]
    quote: str


class ClaimItem(_Output):
    kind: Literal["firm_name", "regulator", "licence_ref", "address", "other"]
    value: str
    quote: str


class RelevanceItem(_Output):
    regulator: Regulator
    status: RelevanceStatus
    rule_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class JurisdictionOutput(_Conversational):
    activities: list[ActivityItem] = Field(default_factory=list)
    zone_signals: list[ZoneItem] = Field(default_factory=list)
    claims: list[ClaimItem] = Field(default_factory=list)
    targets_uae_clients: Literal["yes", "no", "unclear"] | None = None
    relevance: list[RelevanceItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- Regulator agents


class OwnRelevance(_Output):
    status: RelevanceStatus
    rule_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class RegisterItem(_Output):
    evidence_id: str
    match_type: Literal["exact", "alias", "fuzzy", "partial", "reference"]
    status: LicenceStatusValue
    second_identifier: str | None = None
    rationale: str = ""


class ScopeItem(_Output):
    entity_evidence_id: str
    activity: str
    covered: CoveredValue
    rule_id: str | None = None
    rationale: str = ""


class AlertItem(_Output):
    evidence_id: str
    about: AlertAbout
    matched_on: str
    rationale: str = ""


class RegulatorOutput(_Conversational):
    relevance: OwnRelevance | None = None
    register_matches: list[RegisterItem] = Field(default_factory=list)
    no_match_evidence_ids: list[str] = Field(default_factory=list)
    scope: list[ScopeItem] = Field(default_factory=list)
    alerts: list[AlertItem] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- Clone-check


class ContactItem(_Output):
    cp_id: str
    status: ContactStatus
    official_evidence_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class PaymentItem(_Output):
    beneficiary_matches: bool | None = None
    wallet_requested: bool = False
    iban_country: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class CloneCheckOutput(_Conversational):
    contacts: list[ContactItem] = Field(default_factory=list)
    payment: PaymentItem | None = None


# --------------------------------------------------------------------------- Reconciler


class ResolutionItem(_Output):
    conflict_id: str
    outcome: Literal["upheld", "overturned", "merged", "unresolved"]
    winning_finding_ids: list[str] = Field(default_factory=list)
    precedence_rule: str
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class NewConflictItem(_Output):
    type: ConflictType
    finding_ids: list[str]
    summary: str = ""


class ReconcilerRoundOutput(_Output):
    new_conflicts: list[NewConflictItem] = Field(default_factory=list)
    resolutions: list[ResolutionItem] = Field(default_factory=list)
    challenges: list[OutgoingItem] = Field(default_factory=list)


class RelevantRegulatorItem(_Output):
    regulator: Regulator
    status: RelevanceStatus
    rationale: str = ""


class SynthesisClaimItem(_Output):
    finding_id: str
    text: str


class ReconcilerSynthesisOutput(_Output):
    resolutions: list[ResolutionItem] = Field(default_factory=list)
    relevant_regulators: list[RelevantRegulatorItem] = Field(default_factory=list)
    result: ResultCode
    hard_conflicts: list[str] = Field(default_factory=list)
    unverified_reasons: list[str] = Field(default_factory=list)
    claims: list[SynthesisClaimItem] = Field(default_factory=list)
    explanation: str


# --------------------------------------------------------------------------- Verifier


class EntailmentItem(_Output):
    claim_index: int
    verdict: Literal["supported", "partly_supported", "unsupported"]
    rationale: str = ""


class ContradictionItem(_Output):
    evidence_id: str
    claim_index: int | None = None
    rationale: str = ""


class VerifierOutput(_Output):
    entailment: list[EntailmentItem] = Field(default_factory=list)
    contradictions: list[ContradictionItem] = Field(default_factory=list)

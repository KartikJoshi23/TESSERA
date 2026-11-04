"""The claim catalogue: typed, machine-checkable assertions (implementation-plan.md §6.2.1).

Every finding carries exactly one assertion. Typed assertions let the Verifier compare claims with
evidence fields mechanically (gates G2 and G8), and let the decision-policy engine derive a result
from findings alone.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from tessera.protocol.common import Regulator, RelevanceStatus, Zone

LicenceStatusValue = Literal["active", "ipa", "withdrawn", "suspended", "unknown"]
CoveredValue = Literal["yes", "no", "unknown"]
ContactStatus = Literal[
    "matches_official",
    "lookalike_of_official",
    "alert_listed",
    "not_on_record",
    "not_comparable",
]
AlertAbout = Literal[
    "entity_unauthorised",  # the list names the entity itself as unauthorised or warned
    "impersonation_of_entity",  # the alert names the entity as the impersonated firm
    "contact_listed",  # the list names a contact point used in the offer
    "regulator_impersonation",  # the alert is about someone imitating the regulator
    "other",
]


class _Assertion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActivityClaim(_Assertion):
    """The offered activity, as a code from ``knowledge/taxonomy/activities.yaml``."""

    type: Literal["activity"] = "activity"
    code: str


class ZoneSignal(_Assertion):
    """A signal about where the offer operates from. Claimed, not established."""

    type: Literal["zone_signal"] = "zone_signal"
    zone: Zone
    basis: Literal["address", "name", "domain", "phone", "claim", "other"]


class OfferClaim(_Assertion):
    """Something the offer says about itself."""

    type: Literal["offer_claim"] = "offer_claim"
    kind: Literal["firm_name", "regulator", "licence_ref", "address", "other"]
    value: str


class Targeting(_Assertion):
    """Whether the offer targets UAE clients (the FDL 33 Art. 2(1)(d) question)."""

    type: Literal["targeting"] = "targeting"
    targets_uae_clients: Literal["yes", "no", "unclear"]


class Relevance(_Assertion):
    """Whether a regulator could be relevant. Overlap is allowed (precedence rule P5)."""

    type: Literal["relevance"] = "relevance"
    regulator: Regulator
    status: RelevanceStatus
    rule_ids: tuple[str, ...] = ()


class CoverageGap(_Assertion):
    """Something that could not be checked.

    ``scope="regulator"`` means the regulator's records could not be consulted at all, which rules
    out CONSISTENT (reason U2). ``scope="field"`` notes a missing detail and does not block.
    """

    type: Literal["coverage_gap"] = "coverage_gap"
    regulator: Regulator
    reason: str
    scope: Literal["regulator", "field"] = "regulator"


class RegisterMatch(_Assertion):
    type: Literal["register_match"] = "register_match"
    regulator: Regulator
    entity_evidence_id: str
    match_type: Literal["exact", "alias", "fuzzy", "partial", "reference"]
    #: What confirms a fuzzy match (condition K1), for example "reference_number".
    second_identifier: str | None = None


class RegisterNoMatch(_Assertion):
    type: Literal["register_no_match"] = "register_no_match"
    regulator: Regulator


class LicenceStatus(_Assertion):
    type: Literal["licence_status"] = "licence_status"
    regulator: Regulator
    entity_evidence_id: str
    status: LicenceStatusValue


class LicenceScope(_Assertion):
    type: Literal["licence_scope"] = "licence_scope"
    regulator: Regulator
    entity_evidence_id: str
    activity: str
    covered: CoveredValue
    rule_id: str | None = None


class AlertHit(_Assertion):
    type: Literal["alert_hit"] = "alert_hit"
    source_id: str
    alert_evidence_id: str
    about: AlertAbout
    matched_on: str


class ContactAssessment(_Assertion):
    type: Literal["contact_assessment"] = "contact_assessment"
    cp_id: str
    status: ContactStatus
    official_evidence_id: str | None = None


class PaymentAssessment(_Assertion):
    type: Literal["payment_assessment"] = "payment_assessment"
    beneficiary_matches: bool | None = None
    wallet_requested: bool = False
    iban_country: str | None = None


Assertion = Annotated[
    ActivityClaim
    | ZoneSignal
    | OfferClaim
    | Targeting
    | Relevance
    | CoverageGap
    | RegisterMatch
    | RegisterNoMatch
    | LicenceStatus
    | LicenceScope
    | AlertHit
    | ContactAssessment
    | PaymentAssessment,
    Field(discriminator="type"),
]

ASSERTION_ADAPTER: TypeAdapter[Assertion] = TypeAdapter(Assertion)

#: Judgements and absences. They state no fact from a record, so they have nothing to cite.
_NOTHING_TO_CITE = frozenset({"coverage_gap", "targeting", "relevance"})


def needs_evidence(assertion: Assertion) -> bool:
    """False for an assertion with no record to cite, such as a contact with no comparison."""
    if isinstance(assertion, ContactAssessment):
        return assertion.status != "not_comparable"
    return assertion.type not in _NOTHING_TO_CITE

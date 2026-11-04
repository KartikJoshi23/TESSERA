"""Does each finding's evidence really say what the finding says? (§6.8 G2, §6.6 C6)

Typed assertions are compared with evidence fields mechanically. No model is involved, so an agent
cannot argue its way past these checks. A finding that fails is flagged as conflict type C6, gate
G2 refuses any claim built on it, and the decision-policy engine ignores it.

Restricted evidence holds row references only, so its facts are resolved locally through
``facts_for``, and masked contact points are restored locally. Nothing here leaves the machine.
"""

from __future__ import annotations

# A finding's assertion is a union. Each rule picks findings by type first, so attributes are safe.
# mypy: disable-error-code="union-attr"
import hashlib
from collections.abc import Callable, Iterable
from typing import Any

from tessera.blackboard.board import Blackboard
from tessera.governance.policies import SourcesPolicy
from tessera.normalize.domains import registrable_domain
from tessera.normalize.phones import normalize_phone
from tessera.protocol.claims import (
    AlertHit,
    ContactAssessment,
    LicenceScope,
    LicenceStatus,
    PaymentAssessment,
    RegisterMatch,
    RegisterNoMatch,
    Relevance,
)
from tessera.protocol.contacts import ContactKind, ContactPoint
from tessera.protocol.evidence import REGISTER_SOURCES, EvidenceKind, EvidenceRecord
from tessera.protocol.findings import Finding

FactsFor = Callable[[EvidenceRecord], dict[str, Any]]

LIST_KINDS = frozenset(
    {EvidenceKind.ALERT_ENTRY, EvidenceKind.WARNING_ENTRY, EvidenceKind.UNLICENSED_ENTRY}
)
CONTACT_MATCHES = frozenset({"domain", "phone", "email", "email_domain", "contact_named"})
_NAME_MATCHES = frozenset({"name", "firm_named", "frn_named"})
_DOMAIN_KINDS = frozenset({ContactKind.URL, ContactKind.DOMAIN, ContactKind.EMAIL})
_PHONE_KINDS = frozenset({ContactKind.PHONE, ContactKind.WHATSAPP})
_UNAUTHORISED_CATEGORIES = frozenset({"false_claim_of_authorisation", "unauthorised_firm"})
_DFSA_STATUS = {"authorised": "active", "withdrawn": "withdrawn", "suspended": "suspended"}
_VARA_STATUS = {"LICENSED": "active", "IPA": "ipa"}
_CMA_NOT_ACTIVE = (
    ("suspend", "suspended"),
    ("withdraw", "withdrawn"),
    ("cancel", "withdrawn"),
    ("revok", "withdrawn"),
)


def matched_on(record: EvidenceRecord) -> frozenset[str]:
    """What a list record matched on. Tools record several matches as a comma-separated list."""
    return frozenset(str(record.fields.get("matched_on", "")).split(","))


def official_status(record: EvidenceRecord, facts: dict[str, Any]) -> str | None:
    """The licence status a register entry shows, in the claim catalogue's terms."""
    if record.source_id == "dfsa_register":
        return _DFSA_STATUS.get(str(facts.get("status")))
    status = str(record.fields.get("status") or "")
    if record.source_id == "vara_register":
        return _VARA_STATUS.get(status)
    lowered = status.strip().casefold()
    named = next((value for cue, value in _CMA_NOT_ACTIVE if cue in lowered), None)
    # Only the exact word counts. "Inactive" and "not active" contain it, and mean the opposite.
    return named or ("active" if lowered == "active" else None)


def _key(value: str) -> str:
    """The short hash analysis tools put in their locators, identifying the offer's contact."""
    return hashlib.sha256(value.encode()).hexdigest()[:8]


class ClaimChecker:
    def __init__(self, board: Blackboard, sources: SourcesPolicy, facts_for: FactsFor) -> None:
        self.board = board
        self.sources = sources
        self.facts_for = facts_for
        self._checks: dict[str, Callable[[Finding, Any], list[str]]] = {
            "activity": self._quote,
            "zone_signal": self._quote,
            "offer_claim": self._quote,
            "relevance": self._relevance,
            "register_match": self._register_match,
            "register_no_match": self._register_no_match,
            "licence_status": self._licence_status,
            "licence_scope": self._licence_scope,
            "alert_hit": self._alert_hit,
            "contact_assessment": self._contact,
            "payment_assessment": self._payment,
        }

    def problems(self, finding: Finding) -> list[str]:
        """Why this finding's evidence does not support it. Empty means it does."""
        found = [f"cites evidence no tool created: {e}" for e in finding.unknown_evidence_ids]
        check = self._checks.get(finding.assertion.type)
        return found + (check(finding, finding.assertion) if check else [])

    # ------------------------------------------------------------------ helpers

    def _records(self, finding: Finding) -> list[EvidenceRecord]:
        known = (self.board.evidence.get(e) for e in finding.evidence_ids)
        return [record for record in known if record is not None]

    def _regulator(self, record: EvidenceRecord) -> str | None:
        policy = self.sources.sources.get(record.source_id)
        return policy.regulator if policy else None

    def _entry(
        self, finding: Finding, evidence_id: str, regulator: str
    ) -> tuple[EvidenceRecord | None, list[str]]:
        record = self.board.evidence.get(evidence_id)
        if record is None or evidence_id not in finding.evidence_ids:
            return None, ["the register entry it names is not among its evidence"]
        if record.kind is not EvidenceKind.REGISTER_ENTRY:
            return None, ["the evidence it names is not a register entry"]
        if self._regulator(record) != regulator:
            return None, [f"the register entry is not from {regulator}"]
        return record, []

    def _point(self, cp_id: str) -> ContactPoint | None:
        assert self.board.case is not None
        return next((p for p in self.board.case.contact_points if p.cp_id == cp_id), None)

    def _is_this_contact(self, record: EvidenceRecord, point: ContactPoint) -> bool:
        """True if an analysis record was made for this contact point, and not for another."""
        real = self.board.gateway.unmask(point.normalized)
        if point.kind in _DOMAIN_KINDS:
            value = registrable_domain(real) or real
        elif point.kind in _PHONE_KINDS:
            info = normalize_phone(real)
            value = info.e164 if info else real
        else:
            return False
        return record.locator.split(":")[1:2] == [_key(value)]

    def _is_stated_official(self, record: EvidenceRecord, point: ContactPoint) -> bool:
        """True if a regulator's own record states this contact point as official."""
        if record.kind not in LIST_KINDS or "contact_stated_official" not in matched_on(record):
            return False
        stated = self.facts_for(record).get("official_contacts_stated", [])
        real = self.board.gateway.unmask(point.normalized)
        domain = registrable_domain(real)
        return bool(domain) and domain in {registrable_domain(v.lstrip("@")) for v in stated}

    # ------------------------------------------------------------------ one check per type

    def _quote(self, finding: Finding, _: Any) -> list[str]:
        if any(record.minted_by == "offer_quote" for record in self._records(finding)):
            return []
        return ["no words from the offer back this"]

    def _relevance(self, finding: Finding, a: Relevance) -> list[str]:
        """Only an exclusion needs grounds. Adding a regulator can only make a result cautious."""
        if a.status != "excluded":
            return []
        if any(record.kind is EvidenceKind.RULE_CARD for record in self._records(finding)):
            return []
        return ["an exclusion must cite a rule"]

    def _register_match(self, finding: Finding, a: RegisterMatch) -> list[str]:
        record, problems = self._entry(finding, a.entity_evidence_id, a.regulator)
        if record is not None and record.fields.get("match_type") != a.match_type:
            problems.append(f"the tool reported a {record.fields.get('match_type')} match")
        return problems

    def _register_no_match(self, finding: Finding, a: RegisterNoMatch) -> list[str]:
        for record in self._records(finding):
            if (
                record.kind is EvidenceKind.NO_MATCH
                and record.source_id in REGISTER_SOURCES
                and self._regulator(record) == a.regulator
            ):
                return []
        return [f"no recorded no-match on the {a.regulator} register"]

    def _licence_status(self, finding: Finding, a: LicenceStatus) -> list[str]:
        record, problems = self._entry(finding, a.entity_evidence_id, a.regulator)
        if record is None:
            return problems
        shown = official_status(record, self.facts_for(record)) or "unknown"
        return [] if a.status == shown else [f"the register shows status {shown}"]

    def _licence_scope(self, finding: Finding, a: LicenceScope) -> list[str]:
        record, problems = self._entry(finding, a.entity_evidence_id, a.regulator)
        if record is None:
            return problems
        if a.covered != "unknown":
            rules = {r.locator for r in self._records(finding) if r.kind is EvidenceKind.RULE_CARD}
            if a.rule_id not in rules:
                problems.append("a scope conclusion must cite its rule card")
        facts = self.facts_for(record)
        if a.covered == "yes" and official_status(record, facts) == "ipa":
            problems.append("an In-Principle Approval covers no activity yet")
        if "covers_activities" in facts:
            if a.activity in facts["covers_activities"]:
                shown = "yes"
            else:
                shown = "no" if facts["scope_complete"] else "unknown"
            if a.covered != shown:
                problems.append(f"the tool's scope result for {a.activity} is {shown}")
        return problems

    def _alert_hit(self, finding: Finding, a: AlertHit) -> list[str]:
        record = self.board.evidence.get(a.alert_evidence_id)
        if record is None or a.alert_evidence_id not in finding.evidence_ids:
            return ["the list record it names is not among its evidence"]
        if record.kind not in LIST_KINDS:
            return ["the evidence it names is not a list record"]
        if record.source_id != a.source_id:
            return [f"the record comes from {record.source_id}"]
        on = matched_on(record)
        category = self.facts_for(record).get("category")
        if a.about == "contact_listed" and not on & CONTACT_MATCHES:
            return ["the record does not name a contact point from this offer"]
        if a.about == "entity_unauthorised":
            if not on & _NAME_MATCHES:
                return ["the record does not name this entity"]
            if category is not None and category not in _UNAUTHORISED_CATEGORIES:
                return [f"the record's category is {category}"]
        if (
            a.about == "impersonation_of_entity"
            and category not in (None, "impersonated_authorised_firm")
        ) or (a.about == "regulator_impersonation" and category != "regulator_impersonation"):
            return [f"the record's category is {category}"]
        return []

    def _contact(self, finding: Finding, a: ContactAssessment) -> list[str]:
        point = self._point(a.cp_id)
        if point is None:
            return [f"no contact point {a.cp_id} in this offer"]
        records = self._records(finding)
        official = self.board.evidence.get(a.official_evidence_id or "")
        if a.official_evidence_id and official is None:
            return ["the official record it names does not exist"]
        if a.status == "alert_listed":
            if any(r.kind in LIST_KINDS and matched_on(r) & CONTACT_MATCHES for r in records):
                return []
            return ["no list record names this contact point"]
        if a.status == "matches_official":
            return self._matches_official(records, point)
        if a.status == "lookalike_of_official":
            if official is None:
                return ["a look-alike needs the official record"]
            if any(r.minted_by == "compare_domain" and r.fields.get("lookalike") for r in records):
                return []
            return ["the domain comparison does not report a look-alike"]
        if a.status == "not_on_record" and official is None:
            return ["'not on record' needs the official record it was compared with"]
        return []

    def _matches_official(
        self, records: Iterable[EvidenceRecord], point: ContactPoint
    ) -> list[str]:
        for record in records:
            confirmed = (
                record.fields.get("same_registrable") or record.fields.get("equal_to_official")
            ) and self._is_this_contact(record, point)
            if confirmed or self._is_stated_official(record, point):
                return []
        return ["no comparison shows this contact point matches the official record"]

    def _payment(self, finding: Finding, a: PaymentAssessment) -> list[str]:
        for record in self._records(finding):
            if (
                record.minted_by == "analyse_payment"
                and record.fields.get("beneficiary_matches") == a.beneficiary_matches
                and record.fields.get("wallet_requested") == a.wallet_requested
            ):
                return []
        return ["no payment analysis shows this"]

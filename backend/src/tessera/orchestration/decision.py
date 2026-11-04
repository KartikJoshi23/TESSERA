"""The decision-policy engine: the result the agreed findings support (§4).

The Reconciler applies the policy with judgement, and this engine applies it mechanically. Gate G8
compares the two, so a proposal can never be more reassuring than the evidence allows.

Three deliberate asymmetries keep mistakes on the cautious side:

* A finding whose evidence does not support it counts for nothing, in either direction.
* A hard conflict backed by valid evidence stands even if a challenge to it went unanswered,
  because evidence beats assertion (P1). A finding with an unanswered challenge cannot support
  ``CONSISTENT``.
* The Reconciler's resolutions never remove a valid finding, so it cannot overrule evidence by
  argument (§6.7). They only close conflicts.
"""

from __future__ import annotations

# A finding's assertion is a union. Each rule picks findings by type first, so attributes are safe.
# mypy: disable-error-code="union-attr"
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from tessera.agents.base import AgentEnv
from tessera.normalize.domains import registrable_domain
from tessera.orchestration.support import CONTACT_MATCHES, ClaimChecker, matched_on
from tessera.protocol.claims import DECISIVE_TYPES
from tessera.protocol.common import ResultCode
from tessera.protocol.conflicts import ConflictStatus
from tessera.protocol.contacts import ContactKind, ContactRole
from tessera.protocol.evidence import EvidenceRecord
from tessera.protocol.findings import Finding, FindingStatus
from tessera.protocol.messages import Performative
from tessera.tools.matching import match_name

_DOMAIN_KINDS = frozenset({ContactKind.URL, ContactKind.DOMAIN, ContactKind.EMAIL})
_NOT_ACTIVE = frozenset({"ipa", "withdrawn", "suspended"})


@dataclass(frozen=True)
class HardConflict:
    id: str
    finding_ids: tuple[str, ...]


@dataclass(frozen=True)
class PolicyDecision:
    result: ResultCode
    hard_conflicts: tuple[HardConflict, ...]
    conditions: dict[str, bool]
    unverified_reasons: tuple[str, ...]

    @property
    def hard_conflict_ids(self) -> tuple[str, ...]:
        return tuple(sorted({conflict.id for conflict in self.hard_conflicts}))

    def summary(self) -> dict[str, Any]:
        """A plain record for the event log. It holds rule and finding IDs only."""
        return {
            "result": self.result.value,
            "hard_conflicts": {c.id: list(c.finding_ids) for c in self.hard_conflicts},
            "conditions": self.conditions,
            "unverified_reasons": list(self.unverified_reasons),
        }


def _regulator_named(claim: str, names: dict[str, tuple[str, ...]]) -> str | None:
    """The regulator a claim names, as whole words, so "regulated by the DFSA" counts."""
    text = " ".join(claim.casefold().split())
    return next(
        (
            code
            for code, aliases in names.items()
            if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) for alias in aliases)
        ),
        None,
    )


class DecisionEngine:
    def __init__(self, env: AgentEnv, today: date) -> None:
        self.env = env
        self.board = env.board
        self.today = today
        self.checker = ClaimChecker(env.board, env.ctx.sources, env.facts_for)
        self.live = env.board.live_findings()
        self.invalid = {f.finding_id for f in self.live if self.checker.problems(f)}
        self.relevant = env.board.relevant_regulators()

    # ------------------------------------------------------------------ what can be relied on

    def valid(self, kind: str) -> list[Finding]:
        return [
            f for f in self.live if f.assertion.type == kind and f.finding_id not in self.invalid
        ]

    def _unanswered(self, finding: Finding) -> bool:
        return finding.status is FindingStatus.CHALLENGED and any(
            m.performative is Performative.CHALLENGE
            and finding.finding_id in m.refs
            and m.msg_id not in self.board.answered
            for m in self.board.messages
        )

    def trusted(self, kind: str) -> list[Finding]:
        """Valid findings that can support ``CONSISTENT``: no challenge to them went unanswered."""
        return [f for f in self.valid(kind) if not self._unanswered(f)]

    def _record(self, evidence_id: str) -> EvidenceRecord:
        return self.board.evidence[evidence_id]

    def _unresolved_findings(self) -> set[str]:
        return {
            finding_id
            for conflict in self.board.conflicts.values()
            if conflict.status in (ConflictStatus.OPEN, ConflictStatus.UNRESOLVED)
            for finding_id in conflict.finding_ids
        }

    def _has_unresolved_conflict(self) -> bool:
        return any(
            c.status in (ConflictStatus.OPEN, ConflictStatus.CHALLENGED, ConflictStatus.UNRESOLVED)
            for c in self.board.conflicts.values()
        )

    # ------------------------------------------------------------------ what the offer claims

    def claimed_names(self) -> list[str]:
        return [
            self.board.gateway.unmask(f.assertion.value)
            for f in self.valid("offer_claim")
            if f.assertion.kind == "firm_name"
        ]

    def claimed_regulators(self) -> list[tuple[Finding, str | None]]:
        names = self.env.decision.regulator_names
        found: list[tuple[Finding, str | None]] = []
        for finding in self.valid("offer_claim"):
            if finding.assertion.kind != "regulator":
                continue
            found.append((finding, _regulator_named(finding.assertion.value, names)))
        return found

    def _reference_mismatch(self, match: Finding) -> bool:
        """True if a claimed reference number belongs to a firm with a different name."""
        if match.assertion.match_type != "reference":
            return False
        claimed = self.claimed_names()
        if not claimed:
            return False
        evidence = self._record(match.assertion.entity_evidence_id)
        record = self.env.ctx.registry.table(evidence.source_id).get(evidence.locator)
        if record is None:
            return False
        t = self.env.decision.thresholds
        for name in claimed:
            matches = match_name(
                name,
                [("entity", record.names())],
                tau1=t.name_fuzzy_tau1,
                tau2=t.name_partial_tau2,
                partial_min_length=t.partial_min_length,
            )
            if matches and matches[0].match_type in ("exact", "alias", "fuzzy"):
                return False
        return True

    # ------------------------------------------------------------------ hard conflicts

    def _names_contact(self, finding: Finding) -> bool:
        record = self._record(finding.assertion.alert_evidence_id)
        return bool(matched_on(record) & CONTACT_MATCHES)

    def _cites_lookalike(self, contact: Finding) -> bool:
        return any(
            self.board.evidence[e].minted_by == "compare_domain"
            and self.board.evidence[e].fields.get("lookalike")
            for e in contact.evidence_ids
            if e in self.board.evidence
        )

    def _contact_outside_stated(self) -> list[tuple[Finding, Finding]]:
        """Contacts that differ from the ones a regulator itself states as official (HC5)."""
        found: list[tuple[Finding, Finding]] = []
        assert self.board.case is not None
        points = {p.cp_id: p for p in self.board.case.contact_points}
        for alert in self.valid("alert_hit"):
            if alert.assertion.about != "impersonation_of_entity":
                continue
            stated = self.env.facts_for(self._record(alert.assertion.alert_evidence_id)).get(
                "official_contacts_stated", []
            )
            official = {registrable_domain(value.lstrip("@")) for value in stated} - {None}
            if not official:
                continue
            for contact in self.valid("contact_assessment"):
                point = points[contact.assertion.cp_id]
                if contact.assertion.status != "not_on_record" or point.kind not in _DOMAIN_KINDS:
                    continue
                real = self.board.gateway.unmask(point.normalized)
                if registrable_domain(real) not in official:
                    found.append((contact, alert))
        return found

    def hard_conflicts(self) -> list[HardConflict]:
        found: list[HardConflict] = []

        def add(rule: str, *findings: Finding) -> None:
            found.append(HardConflict(rule, tuple(f.finding_id for f in findings)))

        for contact in self.valid("contact_assessment"):
            status = contact.assertion.status
            if status == "alert_listed":
                add("HC1", contact)
            # Clone-check reports only the first status that applies, so an alert-listed contact
            # can also be a look-alike. Its cited comparison shows that.
            if status == "lookalike_of_official" or (
                status == "alert_listed" and self._cites_lookalike(contact)
            ):
                add("HC5", contact)
        for contact, alert in self._contact_outside_stated():
            add("HC5", contact, alert)
        for alert in self.valid("alert_hit"):
            about = alert.assertion.about
            if about == "contact_listed" or (
                about == "regulator_impersonation" and self._names_contact(alert)
            ):
                add("HC1", alert)
            elif about == "entity_unauthorised":
                record = self._record(alert.assertion.alert_evidence_id)
                if record.fields.get("match_type") in ("exact", "alias"):
                    add("HC2", alert)
        self._contradicted_claims(add)
        for scope in self.valid("licence_scope"):
            if scope.assertion.covered == "no":
                add("HC4", scope)
        offered = any(f.assertion.type == "activity" for f in self.live)
        for status in self.valid("licence_status"):
            if status.assertion.status == "ipa" and offered:
                add("HC4", status)  # an In-Principle Approval holder may not serve clients
        for payment in self.valid("payment_assessment"):
            if payment.assertion.beneficiary_matches is False:
                add("HC6", payment)
        # P7: a hard conflict stands only if it does not rest on an unresolved point.
        unresolved = self._unresolved_findings()
        return [c for c in found if not unresolved & set(c.finding_ids)]

    def _contradicted_claims(self, add: Any) -> None:
        """HC3. A firm that is not found is a conflict only if the offer claims authorisation."""
        names = self.claimed_names()
        for claim, code in self.claimed_regulators():
            if code is None or code not in self.env.covered_regulators:
                continue
            matches = [m for m in self.valid("register_match") if m.assertion.regulator == code]
            absent = [n for n in self.valid("register_no_match") if n.assertion.regulator == code]
            if names and absent and not matches:
                add("HC3", claim, *absent)
            for status in self.valid("licence_status"):
                if status.assertion.regulator == code and status.assertion.status in _NOT_ACTIVE:
                    add("HC3", claim, status)
        for match in self.valid("register_match"):
            if self._reference_mismatch(match):
                add("HC3", match)

    # ------------------------------------------------------------------ conditions

    def _entities(self) -> dict[tuple[str, str], list[Finding]]:
        groups: dict[tuple[str, str], list[Finding]] = {}
        for match in self.trusted("register_match"):
            if self._reference_mismatch(match):
                continue
            record = self._record(match.assertion.entity_evidence_id)
            groups.setdefault((record.source_id, record.locator), []).append(match)
        return groups

    @staticmethod
    def _confirmed(match: Finding) -> bool:
        assertion = match.assertion
        return assertion.match_type in ("exact", "alias", "reference") or bool(
            assertion.second_identifier
        )

    def _entity_is_competent_and_active(self, matches: list[Finding]) -> tuple[bool, bool]:
        """K2 and K3 for the one matched entity."""
        first = matches[0].assertion
        entity = self._record(first.entity_evidence_id).locator

        def same_entity(finding: Finding) -> bool:
            return (
                self._record(finding.assertion.entity_evidence_id).locator == entity
                and finding.assertion.regulator == first.regulator
            )

        competent = first.regulator in self.relevant
        statuses = [s for s in self.trusted("licence_status") if same_entity(s)]
        covered = {
            s.assertion.activity
            for s in self.trusted("licence_scope")
            if same_entity(s) and s.assertion.covered == "yes"
        }
        offered = {a.assertion.code for a in self.live if a.assertion.type == "activity"}
        offered.discard("OTHER")
        active = bool(statuses) and all(s.assertion.status == "active" for s in statuses)
        return competent, active and bool(offered) and offered <= covered

    def _contacts_match(self) -> bool:
        """K4: every deciding contact point matches. An offer with none proves nothing."""
        assert self.board.case is not None
        points = self.board.case.contact_points
        if any(p.role is ContactRole.NOT_COMPARABLE for p in points):
            return False
        deciding = [p for p in points if p.role is ContactRole.DECIDING]
        assessed: dict[str, set[str]] = {}
        for contact in self.trusted("contact_assessment"):
            assessed.setdefault(contact.assertion.cp_id, set()).add(contact.assertion.status)
        return bool(deciding) and all(
            assessed.get(point.cp_id) == {"matches_official"} for point in deciding
        )

    def _no_adverse_hits(self) -> bool:
        """K5. An alert naming the entity as the impersonated firm does not block by itself."""
        adverse = {"contact_listed", "entity_unauthorised", "regulator_impersonation"}
        hits = [f for f in self.valid("alert_hit") if f.assertion.about in adverse]
        listed = [
            f for f in self.valid("contact_assessment") if f.assertion.status == "alert_listed"
        ]
        return not hits and not listed and not self._has_unresolved_conflict()

    def _gaps(self) -> tuple[set[str], set[Any]]:
        """Relevant regulators outside coverage, and covered ones whose check did not run."""
        claimed = {code for _, code in self.claimed_regulators() if code is not None}
        uncovered = (self.relevant | claimed) - set(self.env.covered_regulators)
        unchecked = {
            f.assertion.regulator
            for f in self.live
            if f.assertion.type == "coverage_gap"
            and f.assertion.scope == "regulator"
            and f.assertion.regulator in self.relevant
        }
        return uncovered, unchecked - uncovered

    def _stale(self) -> bool:
        limit = self.today - timedelta(days=self.env.decision.thresholds.staleness_days)
        return any(
            record.snapshot_date is not None and record.snapshot_date < limit
            for record in self.board.evidence.values()
        )

    def decide(self, *, veto_standing: bool = False) -> PolicyDecision:
        hard = self.hard_conflicts()
        entities = self._entities()
        matches = next(iter(entities.values())) if len(entities) == 1 else []
        identity = bool(matches) and any(self._confirmed(m) for m in matches)
        competent, active = (
            self._entity_is_competent_and_active(matches) if matches else (False, False)
        )
        uncovered, unchecked = self._gaps()
        decisive = [f for f in self.live if f.assertion.type in DECISIVE_TYPES]
        conditions = {
            "K1": identity,
            "K2": competent,
            "K3": active,
            "K4": self._contacts_match(),
            "K5": self._no_adverse_hits(),
            "K6": not uncovered and not unchecked,
            "K7": not any(f.finding_id in self.invalid for f in decisive),
        }
        unclaimed = any(code is None for _, code in self.claimed_regulators())
        trouble = bool(self.board.failures) or self._stale() or not conditions["K7"] or unchecked

        reasons: list[str] = []
        if not entities and not uncovered:
            reasons.append("U1")
        if uncovered:
            reasons.append("U2")
        assert self.board.case is not None
        short_link = any(
            p.role is ContactRole.NOT_COMPARABLE for p in self.board.case.contact_points
        )
        if not conditions["K4"] and (entities or short_link):
            reasons.append("U3")
        if len(entities) > 1 or (matches and not identity):
            reasons.append("U4")
        if self._has_unresolved_conflict():
            reasons.append("U5")
        if veto_standing:
            reasons.append("U6")
        if trouble:
            reasons.append("U7")
        if unclaimed:
            reasons.append("U8")
        if identity and not (competent and active):
            reasons.append("U9")

        if hard:
            result = ResultCode.CONFLICTS
        elif all(conditions.values()) and not reasons:
            result = ResultCode.CONSISTENT
        else:
            result = ResultCode.UNVERIFIED
        return PolicyDecision(result, tuple(hard), conditions, tuple(reasons))


def derive_decision(env: AgentEnv, *, today: date, veto_standing: bool = False) -> PolicyDecision:
    return DecisionEngine(env, today).decide(veto_standing=veto_standing)

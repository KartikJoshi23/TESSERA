"""RULES-ONLY: lookups and the decision policy, with no model at all (§10.2).

This is the reference floor, and it also probes how hard a dataset is: if plain rules score very
high, the synthetic messages are too formulaic (§11.2 D).

:class:`ToolCrew` does every agent's job through the real tools, given a :class:`Reading` of the
offer. :func:`read_offer` makes that reading from keywords and patterns, which is exactly where a
model has the advantage. The tests give :class:`ToolCrew` a hand-made reading instead, which shows
what the policy reaches when an offer is read perfectly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from tessera.agents.base import AgentEnv
from tessera.agents.reconciler import ReconcilerAgent
from tessera.agents.regulators import build_regulator_agents
from tessera.agents.schemas import ReconcilerSynthesisOutput
from tessera.normalize.names import normalize_name
from tessera.orchestration.decision import PolicyDecision, derive_decision
from tessera.orchestration.support import official_status
from tessera.protocol.claims import (
    DECISIVE_TYPES,
    ActivityClaim,
    AlertHit,
    ContactAssessment,
    CoverageGap,
    LicenceScope,
    LicenceStatus,
    OfferClaim,
    PaymentAssessment,
    RegisterMatch,
    RegisterNoMatch,
    Relevance,
    describe,
)
from tessera.protocol.common import REGULATORS, AgentId, ResultCode
from tessera.protocol.contacts import ContactKind, ContactPoint, ContactRole
from tessera.protocol.evidence import EvidenceRecord
from tessera.protocol.results import FinalResult, ProposedResult, ResultClaim
from tessera.reporting.report import compose_final
from tessera.tools.extract import detect_zone

SCOPE_RULES = {"CMA": "SCOPE-CMA-02", "DFSA": "SCOPE-DFSA-01", "VARA": "SCOPE-VARA-01"}
_AGENTS = {"CMA": AgentId.CMA, "DFSA": AgentId.DFSA, "VARA": AgentId.VARA}
_DOMAIN_KINDS = (ContactKind.URL, ContactKind.DOMAIN, ContactKind.EMAIL)
_PHONE_KINDS = (ContactKind.PHONE, ContactKind.WHATSAPP)
_ALERT_ABOUT = {
    "impersonated_authorised_firm": "impersonation_of_entity",
    "false_claim_of_authorisation": "entity_unauthorised",
    "unauthorised_firm": "entity_unauthorised",
    "regulator_impersonation": "regulator_impersonation",
}


@dataclass(frozen=True)
class Reading:
    """What is taken from the offer's text. A model does this in the crew."""

    activities: tuple[tuple[str, str], ...]  # activity code, words from the offer
    relevant: dict[str, str]
    firm: str | None = None
    regulator: tuple[str, str] | None = None  # as claimed, words from the offer
    reference: str | None = None
    #: The rule that puts an activity outside the licence, where one does.
    not_covered: dict[str, str] = field(default_factory=dict)
    payment: dict[str, Any] | None = None


class ToolCrew:
    """Every agent's job, done through the real tools, posting what the prompts ask for."""

    def __init__(self, env: AgentEnv, reading: Reading, *, author: AgentId | None = None) -> None:
        self.env = env
        self.board = env.board
        self.reading = reading
        self.author = author
        self.entries: list[tuple[str, str]] = []  # regulator, evidence ID

    def _agent(self, agent: AgentId) -> AgentId:
        return self.author or agent

    def call(self, tool: str, actor: AgentId, **arguments: Any) -> dict[str, Any]:
        """Call a tool the way an agent does, in the masked world."""
        masked = self.board.gateway.mask_payload(arguments)
        content, ok = self.env.belt.execute(
            tool, json.dumps(masked), allowed=(tool,), actor=self._agent(actor)
        )
        return json.loads(content) if ok else {}

    def quoted(self, words: str) -> list[str]:
        return self.env.quote_evidence(self.board.gateway.mask(words))

    def deciding(self) -> list[ContactPoint]:
        assert self.board.case is not None
        return [p for p in self.board.case.contact_points if p.role is ContactRole.DECIDING]

    def real(self, point: ContactPoint) -> str:
        return self.board.gateway.unmask(point.normalized)

    def first_domain(self) -> str | None:
        return next((self.real(p) for p in self.deciding() if p.kind in _DOMAIN_KINDS), None)

    # ------------------------------------------------------------------ the crew's turns

    def jurisdiction(self) -> None:
        reading, board, author = self.reading, self.board, self._agent(AgentId.JUR)
        for code, words in reading.activities:
            board.post_finding(author, ActivityClaim(code=code), evidence_ids=self.quoted(words))
        if reading.firm:
            board.post_finding(
                author,
                OfferClaim(kind="firm_name", value=board.gateway.mask(reading.firm)),
                evidence_ids=self.quoted(reading.firm),
            )
        if reading.regulator:
            value, words = reading.regulator
            board.post_finding(
                author, OfferClaim(kind="regulator", value=value), evidence_ids=self.quoted(words)
            )
        for regulator in REGULATORS:
            status = reading.relevant.get(regulator, "not_indicated")
            board.post_finding(
                author,
                Relevance(regulator=regulator, status=status, rule_ids=("JUR-08",)),
                evidence_ids=self.env.rule_evidence(("JUR-08",)),
            )
            if status != "not_indicated" and regulator not in self.env.covered_regulators:
                board.post_finding(
                    AgentId.ORC, CoverageGap(regulator=regulator, reason="not covered")
                )

    def _register_terms(self, regulator: str) -> dict[str, str]:
        reference = {"CMA": "licence_no", "VARA": "licence_ref", "DFSA": "frn"}[regulator]
        terms = {}
        if self.reading.firm:
            terms["name"] = self.reading.firm
        if self.reading.reference:
            terms[reference] = self.reading.reference
        if not terms and (domain := self.first_domain()):
            terms["domain"] = domain
        return terms

    def scope_of(self, regulator: str, code: str, record: EvidenceRecord) -> tuple[str, str]:
        """Whether a licence covers an activity, and the rule that says so."""
        rule_id = self.reading.not_covered.get(code, SCOPE_RULES[regulator])
        return ("no" if code in self.reading.not_covered else "yes"), rule_id

    def _matched(self, regulator: str, matches: list[dict[str, Any]]) -> None:
        board, agent = self.board, self._agent(_AGENTS[regulator])
        for match in matches[:1]:
            evidence = match["evidence_id"]
            record = board.evidence[evidence]
            post = board.post_finding(
                agent,
                RegisterMatch(
                    regulator=regulator,
                    entity_evidence_id=evidence,
                    match_type=match["match_type"],
                ),
                evidence_ids=[evidence],
            )
            status = official_status(record, self.env.facts_for(record)) or "unknown"
            board.post_finding(
                agent,
                LicenceStatus(regulator=regulator, entity_evidence_id=evidence, status=status),
                evidence_ids=[evidence],
                depends_on=(post.finding_id,),
            )
            self.entries.append((regulator, evidence))
            for code, _ in self.reading.activities:
                covered, rule_id = self.scope_of(regulator, code, record)
                board.post_finding(
                    agent,
                    LicenceScope(
                        regulator=regulator,
                        entity_evidence_id=evidence,
                        activity=code,
                        covered=covered,
                        rule_id=rule_id,
                    ),
                    evidence_ids=[evidence, *self.env.rule_evidence((rule_id,))],
                )

    def _alert(self, agent: AgentId, source: str, evidence: str, about: str, on: str) -> None:
        self.board.post_finding(
            self._agent(agent),
            AlertHit(source_id=source, alert_evidence_id=evidence, about=about, matched_on=on),
            evidence_ids=[evidence],
        )

    def _no_match(self, regulator: str, result: dict[str, Any]) -> None:
        evidence = result.get("no_match_evidence_id")
        if evidence:
            self.board.post_finding(
                self._agent(_AGENTS[regulator]),
                RegisterNoMatch(regulator=regulator),
                evidence_ids=[evidence],
            )

    def _opinion(self, regulator: str) -> None:
        status = self.reading.relevant.get(regulator, "not_indicated")
        self.board.post_finding(
            self._agent(_AGENTS[regulator]),
            Relevance(regulator=regulator, status=status, rule_ids=("JUR-08",)),
            evidence_ids=self.env.rule_evidence(("JUR-08",)),
        )

    def _lists(self, agent: AgentId, tool: str, source: str) -> None:
        terms = {"name": self.reading.firm, "domain": self.first_domain()}
        result = self.call(tool, agent, **{k: v for k, v in terms.items() if v})
        for hit in result.get("matches", []):
            named = hit["matched_on"] == "name"
            about = "entity_unauthorised" if named else "contact_listed"
            self._alert(agent, source, hit["evidence_id"], about, hit["matched_on"])

    def cma(self) -> None:
        self._opinion("CMA")
        if terms := self._register_terms("CMA"):
            register = self.call("cma_register_lookup", AgentId.CMA, **terms)
            self._matched("CMA", register.get("matches", []))
            self._no_match("CMA", register)
        self._lists(AgentId.CMA, "cma_warnings_lookup", "cma_warnings")

    def vara(self) -> None:
        self._opinion("VARA")
        if terms := self._register_terms("VARA"):
            register = self.call("vara_register_lookup", AgentId.VARA, **terms)
            self._matched("VARA", register.get("matches", []))
            self._no_match("VARA", register)
        self._lists(AgentId.VARA, "vara_unlicensed_lookup", "vara_unlicensed")

    def dfsa(self) -> None:
        self._opinion("DFSA")
        reading, agent = self.reading, AgentId.DFSA
        terms = {"name": reading.firm, "frn": reading.reference, "domain": self.first_domain()}
        result = self.call("dfsa_facts_lookup", agent, **{k: v for k, v in terms.items() if v})
        self._matched("DFSA", result.get("register_matches", []))
        self._no_match("DFSA", result)
        for alert in result.get("alert_matches", []):
            self._alert(
                agent,
                "dfsa_alerts",
                alert["evidence_id"],
                _ALERT_ABOUT.get(alert["category"], "other"),
                alert["matched_on"],
            )

    def clone_check(self) -> None:
        contacts = [
            self.call("official_contacts_for", AgentId.CLN, evidence_id=evidence)
            for _, evidence in self.entries
        ]
        entry = self.entries[0][1] if self.entries else None
        for point in self.deciding():
            self._assess(point, contacts[0] if contacts else None, entry)
        if self.reading.payment:
            analysis = self.call(
                "analyse_payment",
                AgentId.CLN,
                **self.reading.payment,
                **({"entity_evidence_id": entry} if entry else {}),
            )
            if analysis:
                self.board.post_finding(
                    self._agent(AgentId.CLN),
                    PaymentAssessment(
                        beneficiary_matches=analysis.get("beneficiary_matches"),
                        wallet_requested=analysis.get("wallet_requested", False),
                        iban_country=analysis.get("iban_country"),
                    ),
                    evidence_ids=[analysis["evidence_id"]],
                )

    def _assess(self, point: ContactPoint, official: Any, entry: str | None) -> None:
        real = self.real(point)
        cited: list[str] = []
        status = "not_comparable"
        stated = None
        if point.kind in (*_DOMAIN_KINDS, *_PHONE_KINDS):
            hits = self.call("reverse_contact_lookup", AgentId.CLN, value=real).get("hits", [])
            listed = [h for h in hits if h["matched_on"] != "contact_stated_official"]
            stated = next((h for h in hits if h["matched_on"] == "contact_stated_official"), None)
            cited += [h["evidence_id"] for h in listed]
            if listed:
                status = "alert_listed"
        if official and entry:
            status, compared = self._compare(point, real, official, entry, status)
            cited += compared
        if stated and status in ("not_comparable", "not_on_record"):
            status = "matches_official"
            cited.append(stated["evidence_id"])
        self.board.post_finding(
            self._agent(AgentId.CLN),
            ContactAssessment(
                cp_id=point.cp_id,
                status=status,
                official_evidence_id=entry if status != "not_comparable" else None,
            ),
            evidence_ids=[*([entry] if entry else []), *cited],
        )

    def _compare(
        self, point: ContactPoint, real: str, official: dict[str, Any], entry: str, status: str
    ) -> tuple[str, list[str]]:
        gateway = self.board.gateway
        cited: list[str] = []
        found = "not_on_record"
        if point.kind in _DOMAIN_KINDS:
            for domain in (*official.get("domains", ()), *official.get("email_domains", ())):
                result = self.call(
                    "compare_domain",
                    AgentId.CLN,
                    offer_domain=real,
                    official_domain=gateway.unmask(domain),
                    official_evidence_id=entry,
                )
                cited += [result["evidence_id"]] if result else []
                if result.get("same_registrable"):
                    found = "matches_official"
                elif result.get("lookalike") and found == "not_on_record":
                    found = "lookalike_of_official"
        elif point.kind in _PHONE_KINDS:
            result = self.call(
                "analyse_phone",
                AgentId.CLN,
                offer_phone=real,
                official_phones=[gateway.unmask(phone) for phone in official.get("phones", ())],
                official_evidence_id=entry,
            )
            cited += [result["evidence_id"]] if result else []
            if result.get("equal_to_official"):
                found = "matches_official"
        return (status if status == "alert_listed" else found), cited

    def run(self) -> None:
        self.jurisdiction()
        self.cma()
        self.dfsa()
        self.vara()
        self.clone_check()


# ---------------------------------------------------------------------- reading an offer by rule

_FIRM_WORDS = (
    r"L\.?L\.?C\.?|FZE|FZCO|FZ-LLC|PJSC|Ltd\.?|Limited|Partners|Capital|Securities|Exchange|"
    r"Digital|Wealth|Finance|Brokers|Markets|Hub|Custody|Advisers|Horizon"
)
_FIRM = re.compile(rf"((?:[A-Z][\w&'-]*\s+){{1,5}}(?:\(\w+\)\s+)?(?:{_FIRM_WORDS}))(?![\w-])")
_CLAIM = re.compile(
    r"(?i:licen[sc]ed|regulated|authori[sz]ed)\s+(?i:by|under)\s+(?i:the\s+)?"
    r"([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*)"
)
_CLAIM_BEFORE = re.compile(
    r"\b(CMA|SCA|DFSA|VARA)\b\s+(?:licen[sc]ed|regulated|Firm Reference)"
    r"|licen[sc]ed\s+(CMA|SCA|DFSA|VARA)\b"
)
_BENEFICIARY = re.compile(r"beneficiary\s+([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*)*)")
_WALLET = re.compile(r"\b(?:wallet|usdt|trc20|erc20)\b", re.IGNORECASE)
#: Words a register uses for an activity, in our own short terms.
_REGISTER_WORDS = {
    "DER.FX_CFD": ("otc derivatives", "currencies"),
    "SEC.BROKERAGE": ("securities dealing", "trading broker"),
    "SEC.ADVICE": ("financial consultation",),
    "SEC.PROMOTION": ("promotion", "introduction"),
    "FUND.MGMT": ("fund management",),
    "VA.EXCHANGE": ("exchange",),
    "VA.BROKER": ("broker-dealer",),
    "VA.CUSTODY": ("custody",),
    "VA.TRANSFER": ("transfer",),
}
#: The starting matrix in implementation-plan.md Appendix A.
_MATRIX: dict[str, dict[str, dict[str, str]]] = {
    "DIFC": {group: {"DFSA": "primary"} for group in ("virtual_assets", "capital_markets")},
    "ADGM": {group: {"FSRA": "primary"} for group in ("virtual_assets", "capital_markets")},
    "DUBAI_NON_DIFC": {
        "virtual_assets": {"VARA": "primary", "CMA": "possible"},
        "capital_markets": {"CMA": "primary"},
    },
    "OTHER_EMIRATE": {
        "virtual_assets": {"CMA": "primary"},
        "capital_markets": {"CMA": "primary"},
    },
    "OUTSIDE_UAE": {
        "virtual_assets": {"CMA": "primary", "VARA": "possible"},
        "capital_markets": {"CMA": "primary"},
    },
    "UNKNOWN": {
        "virtual_assets": {
            "VARA": "possible",
            "CMA": "possible",
            "DFSA": "possible",
            "FSRA": "possible",
        },
        "capital_markets": {"CMA": "possible", "DFSA": "possible", "FSRA": "possible"},
    },
}
_BANKING: dict[str, dict[str, str]] = {
    "DIFC": {"DFSA": "primary"},
    "ADGM": {"FSRA": "primary"},
    "UNKNOWN": {"CBUAE": "possible", "DFSA": "possible", "FSRA": "possible"},
}


def _known_firm(env: AgentEnv, text: str) -> str | None:
    """The longest register or list name that appears in the offer."""
    words = " ".join(normalize_name(text).core_tokens)
    found: list[str] = []
    for source_id, policy in env.ctx.sources.sources.items():
        if not policy.enabled or (policy.restricted and not env.ctx.registry.restricted_allowed):
            continue
        for record in env.ctx.registry.table(source_id).records:
            for name in record.names():
                core = " ".join(normalize_name(name).core_tokens)
                if len(core) >= 6 and re.search(rf"(?<!\w){re.escape(core)}(?!\w)", words):
                    found.append(name)
    return max(found, key=len, default=None)


def _firm_in(text: str, known: str | None) -> str | None:
    """The words the offer itself uses for a firm, so they can be quoted."""
    if known:
        if known.casefold() in text.casefold():
            return known
        core = normalize_name(known).core_tokens
        loose = r"[\s\W]+".join(re.escape(token) for token in core)
        hit = re.search(loose, text, re.IGNORECASE)
        if hit:
            return hit.group(0)
    hit = _FIRM.search(text)
    return hit.group(1).strip() if hit else None


def _regulator_claim(text: str) -> tuple[str, str] | None:
    hit = _CLAIM.search(text) or _CLAIM_BEFORE.search(text)
    if hit is None:
        return None
    return next(group for group in hit.groups() if group), hit.group(0)


def _relevance(env: AgentEnv, text: str, codes: list[str]) -> dict[str, str]:
    assert env.board.case is not None
    addresses = [p for p in env.board.case.contact_points if p.kind is ContactKind.ADDRESS]
    source = env.board.gateway.unmask(addresses[0].normalized) if addresses else text
    zone = detect_zone(source)
    # With no activity keyword the offer may still be financial, and a zone can still be read.
    groups = {a.group for a in env.taxonomy.activities if a.code in codes} or {"capital_markets"}
    relevant: dict[str, str] = {}
    for group in groups:
        table = _BANKING.get(zone, {"CBUAE": "primary"}) if group == "banking_payments" else None
        for regulator, status in (table or _MATRIX.get(zone, {}).get(group, {})).items():
            # Offers can span groups. A regulator keeps the strongest status either one gives it.
            if relevant.get(regulator) != "primary":
                relevant[regulator] = status
    return relevant


def read_offer(env: AgentEnv) -> Reading:
    """Everything a model would read from the text, by keyword and pattern only."""
    assert env.board.case is not None
    text = env.board.gateway.unmask(env.board.case.offer_text)
    lowered = text.casefold()
    found = (
        (activity.code, next((word for word in activity.keywords if word in lowered), None))
        for activity in env.taxonomy.activities
    )
    activities = tuple((code, word) for code, word in found if word)
    codes = [code for code, _ in activities]
    references = [
        env.board.gateway.unmask(point.normalized)
        for point in env.board.case.contact_points
        if point.kind is ContactKind.LICENCE_REF
    ]
    payment: dict[str, Any] = {}
    iban = [p for p in env.board.case.contact_points if p.kind is ContactKind.IBAN]
    if iban:
        payment["iban"] = env.board.gateway.unmask(iban[0].normalized)
    if beneficiary := _BENEFICIARY.search(text):
        payment["beneficiary"] = beneficiary.group(1)
    if _WALLET.search(text):
        payment["wallet_requested"] = True
    return Reading(
        activities=activities,
        relevant=_relevance(env, text, codes),
        firm=_firm_in(text, _known_firm(env, text)),
        regulator=_regulator_claim(text),
        reference=references[0] if references else None,
        payment=payment or None,
    )


class RulesOnly(ToolCrew):
    def __init__(self, env: AgentEnv, reading: Reading) -> None:
        super().__init__(env, reading, author=AgentId.SA)

    def scope_of(self, regulator: str, code: str, record: EvidenceRecord) -> tuple[str, str]:
        facts = self.env.facts_for(record)
        if "covers_activities" in facts:
            if code in facts["covers_activities"]:
                return "yes", "SCOPE-DFSA-01"
            return ("no" if facts["scope_complete"] else "unknown"), "SCOPE-DFSA-01"
        if regulator == "VARA" and official_status(record, facts) == "ipa":
            return "no", "SCOPE-VARA-01"
        activities = " ".join(record.fields.get("activities", [])).casefold()
        words = _REGISTER_WORDS.get(code)
        if not activities or words is None:
            return "unknown", SCOPE_RULES[regulator]
        if any(word in activities for word in words):
            return "yes", SCOPE_RULES[regulator]
        return "no", "SCOPE-CMA-01" if regulator == "CMA" else "SCOPE-VARA-02"

    def _opinion(self, regulator: str) -> None:
        """There is one reader here, so relevance is stated once, by :meth:`jurisdiction`."""

    def _settle_relevance_by_register(self) -> None:
        """With no zone signal, the register a firm is on says which regulator is relevant."""
        if self.entries and set(self.reading.relevant.values()) == {"possible"}:
            regulators = {regulator: "primary" for regulator, _ in self.entries}
            self.reading = replace(self.reading, relevant=regulators)

    def _record_gaps(self) -> None:
        """Data that was not loaded is a gap, as it is when an agent's lookup finds no table."""
        agents = build_regulator_agents()
        for agent in agents.values():
            if agent.regulator in self.env.covered_regulators and not agent._records_consulted(
                self.env
            ):
                self.board.post_finding(
                    AgentId.ORC,
                    CoverageGap(regulator=agent.regulator, reason="not every list was consulted"),
                )

    def run(self) -> None:
        self.cma()
        self.dfsa()
        self.vara()
        self.clone_check()
        self._settle_relevance_by_register()
        self.jurisdiction()
        self._record_gaps()


def _explanation(decision: PolicyDecision, env: AgentEnv) -> str:
    rules = {
        rule.id: rule.text
        for rule in (*env.decision.hard_conflicts, *env.decision.unverified_reasons)
    }
    if decision.result is ResultCode.CONSISTENT:
        return "The offer's firm and contact details match the official record."
    listed = (
        decision.hard_conflict_ids
        if decision.result is ResultCode.CONFLICTS
        else decision.unverified_reasons
    )
    return " ".join(rules[rule] for rule in listed if rule in rules)


def run_rules_only(env: AgentEnv, *, today: date) -> FinalResult:
    """Run an offer with no model. There is no Verifier, because nothing here can overreach."""
    RulesOnly(env, read_offer(env)).run()
    board = env.board
    decision = derive_decision(env, today=today)
    claims = tuple(
        ResultClaim(
            finding_id=finding.finding_id,
            assertion=finding.assertion,
            text=describe(finding.assertion),
            evidence_ids=finding.evidence_ids,
        )
        for finding in board.live_findings()
        if finding.assertion.type in DECISIVE_TYPES and finding.evidence_ids
    )
    output = ReconcilerSynthesisOutput(result=decision.result, explanation="")
    board.post_proposal(
        ProposedResult(
            version=1,
            author=AgentId.SA,
            result=decision.result,
            hard_conflicts=decision.hard_conflict_ids,
            unverified_reasons=decision.unverified_reasons,
            claims=claims,
            regulators=ReconcilerAgent()._coverage(env, output),
            explanation=_explanation(decision, env),
        )
    )
    return board.finalize(compose_final(env, decision, verifier_on=False))

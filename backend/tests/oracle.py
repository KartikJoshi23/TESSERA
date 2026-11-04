"""A careful crew with no model: real tools, and findings posted the way the prompts ask.

It answers one question: if every agent does its job, does the deterministic policy reach each smoke
case's gold result, for the gold reasons? Facts a model would read from the offer are listed by hand
in ``ORACLE``. Everything else comes from the tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from tessera.orchestration.support import official_status
from tessera.protocol.claims import (
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
)
from tessera.protocol.common import REGULATORS, AgentId
from tessera.protocol.contacts import ContactKind, ContactRole

SCOPE_RULES = {"CMA": "SCOPE-CMA-02", "DFSA": "SCOPE-DFSA-01", "VARA": "SCOPE-VARA-01"}
AGENTS = {"CMA": AgentId.CMA, "DFSA": AgentId.DFSA, "VARA": AgentId.VARA}
_DOMAIN_KINDS = (ContactKind.URL, ContactKind.DOMAIN, ContactKind.EMAIL)
_PHONE_KINDS = (ContactKind.PHONE, ContactKind.WHATSAPP)
_ALERT_ABOUT = {
    "impersonated_authorised_firm": "impersonation_of_entity",
    "false_claim_of_authorisation": "entity_unauthorised",
    "unauthorised_firm": "entity_unauthorised",
    "regulator_impersonation": "regulator_impersonation",
}


@dataclass(frozen=True)
class Facts:
    """What a careful reader takes from the offer."""

    activities: tuple[tuple[str, str], ...]  # activity code, words from the offer
    relevant: dict[str, str]
    firm: str | None = None
    regulator: tuple[str, str] | None = None  # as claimed, words from the offer
    reference: str | None = None
    #: The scope judgement for an activity, where the licence does not cover it.
    not_covered: dict[str, str] = field(default_factory=dict)
    payment: dict[str, Any] | None = None


ORACLE: dict[str, Facts] = {
    "S01": Facts(
        ((("DER.FX_CFD"), "spot FX and CFD trading"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities L.L.C.",
    ),
    "S02": Facts(
        (("VA.EXCHANGE", "Trade bitcoin"),),
        {"VARA": "primary"},
        firm="Coral Ledger Exchange FZE",
        regulator=("VARA", "licensed by VARA"),
        reference="VL/26/01/001",
    ),
    "S03": Facts(
        (("SEC.ADVICE", "financial consultation"),),
        {"CMA": "primary"},
        firm="Oasis Bridge Financial Consultancy LLC",
        regulator=("SCA", "licensed by the SCA"),
    ),
    "S04": Facts(
        (("SEC.ADVICE", "advise you on financial products"),),
        {"DFSA": "primary"},
        firm="Lumen Crest Capital (DIFC) Limited",
        reference="F000000",
    ),
    "S05": Facts(
        (("FUND.MGMT", "manages portfolios"),),
        {"DFSA": "primary"},
        firm="Harbour Cedar Asset Management (DIFC) Limited",
        regulator=("DFSA", "regulated by the DFSA"),
    ),
    "S06": Facts(
        (("VA.CUSTODY", "custody for your crypto"),),
        {"VARA": "primary"},
        firm="Azure Dhow Digital FZE",
        regulator=("VARA", "licensed by VARA"),
    ),
    "S07": Facts(
        (("FUND.MGMT", "fund management"),),
        {"CMA": "primary"},
        firm="Desert Lantern Capital PJSC",
        regulator=("CMA", "CMA licensed"),
    ),
    "S08": Facts(
        (("SEC.BROKERAGE", "securities dealing"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities",
    ),
    "S09": Facts(
        (("VA.EXCHANGE", "BTC trading"), ("VA.YIELD", "USDT staking")),
        {"DFSA": "primary", "VARA": "possible", "CMA": "possible"},
        firm="Lumen Crest Capital (DIFC) Limited",
        regulator=("DFSA", "regulated by the DFSA"),
        reference="F000000",
        not_covered={"VA.EXCHANGE": "SCOPE-DFSA-01", "VA.YIELD": "SCOPE-DFSA-01"},
        payment={"wallet_requested": True},
    ),
    "S10": Facts(
        (("DER.FX_CFD", "Trade CFDs and forex"),),
        {"CMA": "primary"},
        firm="Oasis Bridge Financial Consultancy LLC",
        regulator=("CMA", "CMA licensed"),
        not_covered={"DER.FX_CFD": "SCOPE-CMA-01"},
    ),
    "S11": Facts(
        (("VA.CUSTODY", "Store your crypto"),),
        {"VARA": "primary"},
        firm="Saffron Chain Custody FZCO",
        regulator=("VARA", "fully licensed VARA firm"),
        not_covered={"VA.CUSTODY": "SCOPE-VARA-02"},
    ),
    "S12": Facts(
        (("VA.EXCHANGE", "buy and sell USDT"),),
        {"VARA": "primary"},
        firm="Mirage Coin Hub",
    ),
    "S13": Facts(((("DER.FX_CFD"), "forex signals"),), {"CMA": "primary"}),
    "S14": Facts(
        (("FUND.MGMT", "private markets fund"),),
        {"DFSA": "primary"},
        firm="Zenith Harbor Partners",
        regulator=("Dubai Financial Services Authority", "Dubai Financial Services Authority"),
    ),
    "S15": Facts(
        (("DER.FX_CFD", "FX account"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities L.L.C.",
    ),
    "S16": Facts(
        (("FUND.MGMT", "managed portfolios"),),
        {"DFSA": "primary"},
        firm="Cedar Harbour Wealth",
        regulator=("DFSA", "DFSA Firm Reference Number"),
        reference="F000001",
    ),
    "S17": Facts(
        (("DER.FX_CFD", "FX account"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities L.L.C.",
        payment={"iban": "AE07 0331 2345 6789 0123 456", "beneficiary": "XYZ General Trading"},
    ),
    "S18": Facts(
        (("OTHER", "investment account"),),
        {"DFSA": "primary"},
        regulator=("DFSA", "FROM THE DFSA"),
    ),
    "S19": Facts(
        (("VA.EXCHANGE", "Our exchange"),),
        {"VARA": "primary"},
        firm="Northern Dune Digital",
        regulator=("VARA", "licensed by VARA"),
        reference="VL/26/01/001",
    ),
    "S20": Facts(
        (("VA.MGMT", "managed crypto portfolios"),),
        {"VARA": "possible", "CMA": "possible", "DFSA": "possible"},
        firm="Bluewave Horizon",
    ),
    "S21": Facts(
        (("LOAN.CREDIT", "personal loans"),),
        {"CBUAE": "primary"},
        firm="Amber Creek Finance PJSC",
    ),
    "S22": Facts(
        (("FUND.MGMT", "wealth management"),),
        {"FSRA": "primary"},
        firm="Falak Harbour Capital (ADGM) Ltd",
    ),
    "S23": Facts(
        (("DER.FX_CFD", "FX market notes"),),
        {"CMA": "primary"},
        firm="Falcon Ridge Securities L.L.C.",
    ),
    "S24": Facts(
        (("VA.EXCHANGE", "crypto account"),),
        {"VARA": "primary"},
        firm="Coral Ledger Exchange FZE",
    ),
    "S25": Facts(
        (("DER.FX_CFD", "gold CFDs"),),
        {"CMA": "primary"},
        firm="Meridian Dune Brokers LLC",
        regulator=("UAE Financial Trade Authority", "UAE Financial Trade Authority"),
    ),
}


class Oracle:
    def __init__(self, setup: Any, facts: Facts) -> None:
        self.setup = setup
        self.facts = facts
        self.env = setup.env
        self.board = setup.board
        self.mask = setup.gateway.mask
        self.entries: list[tuple[str, str]] = []  # regulator, evidence ID

    def call(self, tool: str, actor: AgentId, **arguments: Any) -> dict[str, Any]:
        masked = self.setup.gateway.mask_payload(arguments)
        content, ok = self.env.belt.execute(tool, json.dumps(masked), allowed=(tool,), actor=actor)
        assert ok, content
        return json.loads(content)

    def quoted(self, words: str) -> list[str]:
        evidence = self.env.quote_evidence(self.mask(words))
        assert evidence, f"not in the offer: {words}"
        return evidence

    def rule(self, *rule_ids: str) -> list[str]:
        return self.env.rule_evidence(rule_ids)

    def deciding(self) -> list[Any]:
        points = self.board.case.contact_points
        return [p for p in points if p.role is ContactRole.DECIDING]

    def first_domain(self) -> str | None:
        return next(
            (
                self.setup.gateway.unmask(p.normalized)
                for p in self.deciding()
                if p.kind in _DOMAIN_KINDS
            ),
            None,
        )

    # ------------------------------------------------------------------ the crew's turns

    def jurisdiction(self) -> None:
        f, board = self.facts, self.board
        for code, words in f.activities:
            board.post_finding(
                AgentId.JUR, ActivityClaim(code=code), evidence_ids=self.quoted(words)
            )
        if f.firm:
            board.post_finding(
                AgentId.JUR,
                OfferClaim(kind="firm_name", value=self.mask(f.firm)),
                evidence_ids=self.quoted(f.firm),
            )
        if f.regulator:
            value, words = f.regulator
            board.post_finding(
                AgentId.JUR,
                OfferClaim(kind="regulator", value=value),
                evidence_ids=self.quoted(words),
            )
        for regulator in REGULATORS:
            status = f.relevant.get(regulator, "not_indicated")
            board.post_finding(
                AgentId.JUR,
                Relevance(regulator=regulator, status=status, rule_ids=("JUR-08",)),
                evidence_ids=self.rule("JUR-08"),
            )
            if status != "not_indicated" and regulator not in self.env.covered_regulators:
                board.post_finding(
                    AgentId.ORC, CoverageGap(regulator=regulator, reason="not covered")
                )

    def _register_terms(self, regulator: str) -> dict[str, str]:
        reference = {"CMA": "licence_no", "VARA": "licence_ref", "DFSA": "frn"}[regulator]
        terms = {}
        if self.facts.firm:
            terms["name"] = self.facts.firm
        if self.facts.reference:
            terms[reference] = self.facts.reference
        if not terms and (domain := self.first_domain()):
            terms["domain"] = domain
        return terms

    def _matched(self, regulator: str, matches: list[dict[str, Any]]) -> None:
        board, agent = self.board, AGENTS[regulator]
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
            for code, _ in self.facts.activities:
                rule_id = self.facts.not_covered.get(code, SCOPE_RULES[regulator])
                board.post_finding(
                    agent,
                    LicenceScope(
                        regulator=regulator,
                        entity_evidence_id=evidence,
                        activity=code,
                        covered="no" if code in self.facts.not_covered else "yes",
                        rule_id=rule_id,
                    ),
                    evidence_ids=[evidence, *self.rule(rule_id)],
                )

    def _alert(self, agent: AgentId, source: str, evidence: str, about: str, on: str) -> None:
        self.board.post_finding(
            agent,
            AlertHit(source_id=source, alert_evidence_id=evidence, about=about, matched_on=on),
            evidence_ids=[evidence],
        )

    def _no_match(self, regulator: str, result: dict[str, Any]) -> None:
        evidence = result.get("no_match_evidence_id")
        if evidence:
            self.board.post_finding(
                AGENTS[regulator], RegisterNoMatch(regulator=regulator), evidence_ids=[evidence]
            )

    def _opinion(self, regulator: str) -> None:
        status = self.facts.relevant.get(regulator, "not_indicated")
        self.board.post_finding(
            AGENTS[regulator],
            Relevance(regulator=regulator, status=status, rule_ids=("JUR-08",)),
            evidence_ids=self.rule("JUR-08"),
        )

    def cma(self) -> None:
        self._opinion("CMA")
        agent, f = AgentId.CMA, self.facts
        terms = self._register_terms("CMA")
        if terms:
            register = self.call("cma_register_lookup", agent, **terms)
            self._matched("CMA", register.get("matches", []))
            self._no_match("CMA", register)
        domain = self.first_domain()
        list_terms = {"name": f.firm, "domain": domain}
        warnings = self.call(
            "cma_warnings_lookup", agent, **{k: v for k, v in list_terms.items() if v}
        )
        for hit in warnings.get("matches", []):
            named = hit["matched_on"] == "name"
            about = "entity_unauthorised" if named else "contact_listed"
            self._alert(agent, "cma_warnings", hit["evidence_id"], about, hit["matched_on"])

    def vara(self) -> None:
        self._opinion("VARA")
        agent, f = AgentId.VARA, self.facts
        terms = self._register_terms("VARA")
        if terms:
            register = self.call("vara_register_lookup", agent, **terms)
            self._matched("VARA", register.get("matches", []))
            self._no_match("VARA", register)
        domain = self.first_domain()
        list_terms = {"name": f.firm, "domain": domain}
        unlicensed = self.call(
            "vara_unlicensed_lookup", agent, **{k: v for k, v in list_terms.items() if v}
        )
        for hit in unlicensed.get("matches", []):
            named = hit["matched_on"] == "name"
            about = "entity_unauthorised" if named else "contact_listed"
            self._alert(agent, "vara_unlicensed", hit["evidence_id"], about, hit["matched_on"])

    def dfsa(self) -> None:
        self._opinion("DFSA")
        agent, f = AgentId.DFSA, self.facts
        terms = {"name": f.firm, "frn": f.reference, "domain": self.first_domain()}
        result = self.call("dfsa_facts_lookup", agent, **{k: v for k, v in terms.items() if v})
        self._matched("DFSA", result.get("register_matches", []))
        if not result.get("register_matches"):
            absent = [
                e
                for e in self.board.evidence.values()
                if e.source_id == "dfsa_register" and e.kind.value == "no_match"
            ]
            for record in absent:
                self.board.post_finding(
                    agent, RegisterNoMatch(regulator="DFSA"), evidence_ids=[record.evidence_id]
                )
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
        if self.facts.payment:
            analysis = self.call(
                "analyse_payment",
                AgentId.CLN,
                **self.facts.payment,
                **({"entity_evidence_id": entry} if entry else {}),
            )
            self.board.post_finding(
                AgentId.CLN,
                PaymentAssessment(
                    beneficiary_matches=analysis.get("beneficiary_matches"),
                    wallet_requested=analysis.get("wallet_requested", False),
                    iban_country=analysis.get("iban_country"),
                ),
                evidence_ids=[analysis["evidence_id"]],
            )

    def _assess(self, point: Any, official: dict[str, Any] | None, entry: str | None) -> None:
        real = self.setup.gateway.unmask(point.normalized)
        cited: list[str] = []
        status = "not_comparable"
        stated = None
        if point.kind in (*_DOMAIN_KINDS, *_PHONE_KINDS):
            hits = self.call("reverse_contact_lookup", AgentId.CLN, value=real).get("hits", [])
            listed = [h for h in hits if h["matched_on"] != "contact_legitimate"]
            stated = next((h for h in hits if h["matched_on"] == "contact_legitimate"), None)
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
            AgentId.CLN,
            ContactAssessment(
                cp_id=point.cp_id,
                status=status,
                official_evidence_id=entry if status != "not_comparable" else None,
            ),
            evidence_ids=[*([entry] if entry else []), *cited],
        )

    def _compare(
        self, point: Any, real: str, official: dict[str, Any], entry: str, status: str
    ) -> tuple[str, list[str]]:
        cited: list[str] = []
        found = "not_on_record"
        if point.kind in _DOMAIN_KINDS:
            for domain in (*official.get("domains", ()), *official.get("email_domains", ())):
                result = self.call(
                    "compare_domain",
                    AgentId.CLN,
                    offer_domain=real,
                    official_domain=self.setup.gateway.unmask(domain),
                    official_evidence_id=entry,
                )
                cited.append(result["evidence_id"])
                if result["same_registrable"]:
                    found = "matches_official"
                elif result["lookalike"] and found == "not_on_record":
                    found = "lookalike_of_official"
        elif point.kind in _PHONE_KINDS:
            result = self.call(
                "analyse_phone",
                AgentId.CLN,
                offer_phone=real,
                official_phones=[
                    self.setup.gateway.unmask(phone) for phone in official.get("phones", ())
                ],
                official_evidence_id=entry,
            )
            cited.append(result["evidence_id"])
            if result["equal_to_official"]:
                found = "matches_official"
        return (status if status == "alert_listed" else found), cited

    def run(self) -> None:
        self.jurisdiction()
        self.cma()
        self.dfsa()
        self.vara()
        self.clone_check()


def run_oracle(setup: Any, key: str) -> Oracle:
    oracle = Oracle(setup, ORACLE[key])
    oracle.run()
    return oracle

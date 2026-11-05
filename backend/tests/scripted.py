"""Helpers for driving the crew with scripted model replies.

Scripted replies speak the masked world, as a real model would: placeholders come from the gateway,
never from hard-coded strings. Replies that depend on earlier results are functions of the request.
"""

from __future__ import annotations

import asyncio
import functools
import json
from collections.abc import Callable, Coroutine
from typing import Any

from tessera.llm.testing import json_reply, tool_reply
from tessera.protocol.common import REGULATORS
from tessera.protocol.contacts import ContactRole

FIRM = "Lumen Crest Capital (DIFC) Limited"
FRN = "F000000"
DOMAIN = "lumencrest-capital.example"
ADDRESS = "Gate Village, DIFC, Dubai"
#: Agents' reasoning. The Verifier must never see it.
REASONING = "a distinctive line of agent reasoning"

_ROLES = {
    "# Your role: Single agent": "SA",  # first, because its prompt also holds the regulator notes
    "# Your role: Jurisdiction agent": "JUR",
    "## Your regulator: CMA": "CMA",
    "## Your regulator: DFSA": "DFSA",
    "## Your regulator: VARA": "VARA",
    "# Your role: Clone-check agent": "CLN",
    "# Your role: Reconciler": "REC",
    "# Your role: Verifier": "VER",
}


def in_loop(test: Callable[..., Coroutine[Any, Any, None]]) -> Callable[..., None]:
    """Run an async test. The suite uses no plugin for this, so nothing extra is installed."""

    @functools.wraps(test)
    def run(*args: Any, **kwargs: Any) -> None:
        asyncio.run(test(*args, **kwargs))

    return run


def agent_of(payload: dict[str, Any]) -> str:
    system = payload["messages"][0]["content"]
    return next(agent for marker, agent in _ROLES.items() if marker in system)


def case_data(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload["messages"][1]["content"]
    return json.loads(text.split("<case_data>\n", 1)[1].split("\n</case_data>", 1)[0])


def tool_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool"]


class Routed:
    """Replies per agent, in whatever order parallel agents' requests arrive."""

    def __init__(self) -> None:
        self.queues: dict[str, list[Any]] = {}

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        reply = self.queues[agent_of(payload)].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply(payload) if callable(reply) else reply


def relevance_items(**statuses: str) -> list[dict[str, Any]]:
    rules = {"CMA": ["JUR-04"], "DFSA": ["JUR-02"], "VARA": ["JUR-01"]}
    return [
        {
            "regulator": regulator,
            "status": statuses.get(regulator, "not_indicated"),
            "rule_ids": rules.get(regulator, []),
            "rationale": REASONING,
        }
        for regulator in REGULATORS
    ]


def jurisdiction_output(**changes: Any) -> dict[str, Any]:
    return {
        "targets_uae_clients": "unclear",
        "relevance": relevance_items(CMA="possible", DFSA="primary", VARA="possible"),
        **changes,
    }


def approve_every_claim(payload: dict[str, Any]) -> dict[str, Any]:
    claims = case_data(payload)["claims"]
    return json_reply(
        {
            "entailment": [
                {"claim_index": claim["claim_index"], "verdict": "supported"} for claim in claims
            ],
            "contradictions": [],
        }
    )


def worked_example(setup: Any) -> dict[str, list[Any]]:
    """The trace in implementation-plan.md §6.10.

    A firm's name and reference number are used with a domain named in an impersonation alert.
    Jurisdiction rules VARA out, VARA challenges that, and Jurisdiction revises. The Reconciler
    settles two conflicts by precedence rules. The Verifier vetoes the word "clone", the Reconciler
    rewords, and the second proposal is approved.
    """
    mask = setup.gateway.mask
    firm, frn, domain = mask(FIRM), mask(FRN), mask(DOMAIN)
    phone = "+447700900123"

    def no_matches(rule: str):
        def reply(payload):
            return json_reply(
                {
                    "relevance": {"status": "possible", "rule_ids": [rule], "rationale": REASONING},
                    "no_match_evidence_ids": [
                        result["no_match_evidence_id"] for result in tool_results(payload)
                    ],
                }
            )

        return reply

    def dfsa_final(payload):
        found = tool_results(payload)[0]
        match, alert = found["register_matches"][0], found["alert_matches"][0]
        entry = match["evidence_id"]
        return json_reply(
            {
                "relevance": {"status": "primary", "rule_ids": ["JUR-02"], "rationale": REASONING},
                "register_matches": [
                    {
                        "evidence_id": entry,
                        "match_type": match["match_type"],
                        "status": "active",
                        "rationale": REASONING,
                    }
                ],
                "scope": [
                    {
                        "entity_evidence_id": entry,
                        "activity": activity,
                        "covered": "no",
                        "rule_id": "SCOPE-DFSA-01",
                        "rationale": REASONING,
                    }
                    for activity in ("VA.EXCHANGE", "VA.YIELD")
                ],
                "alerts": [
                    {
                        "evidence_id": alert["evidence_id"],
                        "about": "impersonation_of_entity",
                        "matched_on": "domain",
                        "rationale": REASONING,
                    }
                ],
                "outgoing": [
                    {
                        "performative": "REQUEST",
                        "to": "CLN",
                        "question": "Compare the offer's website with the official one.",
                    }
                ],
            }
        )

    def vara_final(payload):
        target = next(
            f
            for f in case_data(payload)["jurisdiction_findings"]
            if f["assertion"].get("regulator") == "VARA"
        )
        return json_reply(
            {
                "relevance": {"status": "possible", "rule_ids": ["JUR-01"], "rationale": REASONING},
                "no_match_evidence_ids": [
                    result["no_match_evidence_id"] for result in tool_results(payload)
                ],
                "outgoing": [
                    {
                        "performative": "CHALLENGE",
                        "to": "JUR",
                        "target_finding_id": target["finding_id"],
                        "objection": "claim_not_fact",
                        "question": "Does anything beyond the claimed address exclude VARA?",
                        "rule_ids": ["JUR-01"],
                        "rationale": "The exclusion rests on a claim.",
                    }
                ],
            }
        )

    def jurisdiction_revises(payload):
        message = case_data(payload)["inbox"][0]
        return json_reply(
            {
                "responses": [
                    {
                        "message_id": message["message_id"],
                        "action": "REVISE",
                        "rationale": "The DIFC address is only a claim.",
                        "rule_ids": ["JUR-01"],
                        "revised_fields": {"status": "possible"},
                    }
                ]
            }
        )

    def entry_id():
        return setup.board.live_findings("register_match")[0].assertion.entity_evidence_id

    def clone_compare(payload):
        official = tool_results(payload)[0]
        return tool_reply(
            ("reverse_contact_lookup", {"value": domain}),
            ("reverse_contact_lookup", {"value": phone}),
            (
                "compare_domain",
                {
                    "offer_domain": domain,
                    "official_domain": official["domains"][0],
                    "official_evidence_id": entry_id(),
                },
            ),
            (
                "analyse_phone",
                {
                    "offer_phone": phone,
                    "official_phones": official["phones"],
                    "official_evidence_id": entry_id(),
                },
            ),
            ("analyse_payment", {"wallet_requested": True, "entity_evidence_id": entry_id()}),
        )

    def clone_final(payload):
        _, by_domain, _, compared, by_phone, payment = tool_results(payload)
        alert = by_domain["hits"][0]["evidence_id"]
        contacts = []
        for point in setup.board.case.contact_points:
            if point.role is not ContactRole.DECIDING:
                continue
            is_phone = point.kind.value in ("phone", "whatsapp")
            contacts.append(
                {
                    "cp_id": point.cp_id,
                    "status": "not_on_record" if is_phone else "alert_listed",
                    "official_evidence_id": entry_id(),
                    "evidence_ids": [
                        by_phone["evidence_id"] if is_phone else alert,
                        compared["evidence_id"],
                    ],
                    "rationale": REASONING,
                }
            )
        request = case_data(payload)["inbox"][0]
        return json_reply(
            {
                "contacts": contacts,
                "payment": {
                    "wallet_requested": True,
                    "evidence_ids": [payment["evidence_id"]],
                    "rationale": REASONING,
                },
                "responses": [
                    {
                        "message_id": request["message_id"],
                        "action": "ANSWER",
                        "rationale": "Compared in the contact assessments.",
                    }
                ],
            }
        )

    def reconcile(payload):
        rules = {"C3": "P3", "C5": "P2"}
        return json_reply(
            {
                "resolutions": [
                    {
                        "conflict_id": conflict["conflict_id"],
                        "outcome": "upheld",
                        "precedence_rule": rules[conflict["type"]],
                        "rationale": REASONING,
                    }
                    for conflict in case_data(payload)["open_conflicts"]
                ]
            }
        )

    def synthesis(explanation: str):
        def reply(payload):
            board = setup.board
            chosen = [
                *board.live_findings("register_match"),
                *board.live_findings("alert_hit"),
                *board.live_findings("licence_scope"),
                *board.live_findings("contact_assessment"),
            ]
            return json_reply(
                {
                    "relevant_regulators": [
                        {"regulator": "DFSA", "status": "primary", "rationale": REASONING},
                        {"regulator": "VARA", "status": "possible", "rationale": REASONING},
                        {"regulator": "CMA", "status": "possible", "rationale": REASONING},
                    ],
                    "result": "CONFLICTS",
                    "hard_conflicts": ["HC1", "HC4", "HC5"],
                    "claims": [
                        {"finding_id": f.finding_id, "text": "A neutral sentence about the record."}
                        for f in chosen
                    ],
                    "explanation": explanation,
                }
            )

        return reply

    return {
        "JUR": [
            json_reply(
                jurisdiction_output(
                    activities=[
                        {"code": "VA.EXCHANGE", "quote": "BTC trading", "confidence": "high"},
                        {"code": "VA.YIELD", "quote": "USDT staking", "confidence": "high"},
                    ],
                    zone_signals=[{"zone": "DIFC", "basis": "address", "quote": mask(ADDRESS)}],
                    claims=[
                        {"kind": "firm_name", "value": firm, "quote": firm},
                        {"kind": "regulator", "value": "DFSA", "quote": "regulated by the DFSA"},
                    ],
                    relevance=relevance_items(CMA="possible", DFSA="primary", VARA="excluded"),
                )
            ),
            jurisdiction_revises,
        ],
        "CMA": [
            tool_reply(
                ("cma_register_lookup", {"name": firm}), ("cma_warnings_lookup", {"domain": domain})
            ),
            no_matches("JUR-04"),
        ],
        "VARA": [
            tool_reply(
                ("vara_register_lookup", {"name": firm}),
                ("vara_unlicensed_lookup", {"domain": domain}),
            ),
            vara_final,
        ],
        "DFSA": [
            tool_reply(("dfsa_facts_lookup", {"name": firm, "frn": frn, "domain": domain})),
            dfsa_final,
        ],
        "CLN": [
            lambda payload: tool_reply(("official_contacts_for", {"evidence_id": entry_id()})),
            clone_compare,
            clone_final,
        ],
        "REC": [
            reconcile,
            synthesis("The offer's website is called a clone of the firm's website."),
            synthesis(
                "The offer's website domain is named in a DFSA alert about this firm's name."
            ),
        ],
        "VER": [approve_every_claim],
    }

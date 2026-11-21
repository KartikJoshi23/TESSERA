"""The Clone-check agent: are the offer's contact details the firm's official ones? (§5.2)"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.schemas import CloneCheckOutput, PaymentItem
from tessera.blackboard.views import clone_view
from tessera.llm.prompts import render_rule_cards
from tessera.llm.runner import AgentSpec
from tessera.protocol.claims import ContactAssessment, PaymentAssessment
from tessera.protocol.common import AgentId, clip_words
from tessera.protocol.contacts import ContactRole


def _as_the_tool_found(env: AgentEnv, payment: PaymentItem | None) -> PaymentItem | None:
    """The payment tool's own answer, in place of a model's copy of it.

    A model reading "no match" from the tool can report a mismatch when there was no entry to
    compare with. Nothing here depends on its reading, so the two cannot disagree.
    """
    if payment is None:
        return None
    for evidence_id in payment.evidence_ids:
        record = env.board.evidence.get(evidence_id)
        if record is not None and record.minted_by == "analyse_payment":
            found = {
                "beneficiary_matches": record.fields.get("beneficiary_matches"),
                "wallet_requested": bool(record.fields.get("wallet_requested")),
            }
            return payment.model_copy(update=found)
    return payment


#: With nothing shared, nobody hands this agent a register match, so it finds its own (F72).
#: Without these it could never reach the official record, and CREW-SILO could never be Consistent.
ALONE_TOOLS = ("cma_register_lookup", "dfsa_facts_lookup", "vara_register_lookup")
WORKING_ALONE = (
    "Nothing is shared in this condition, so no register match is given to you. First search the "
    "registers yourself for the firm the offer names, with cma_register_lookup, dfsa_facts_lookup "
    "and vara_register_lookup, and treat each match they return as a register_match."
)


class CloneCheckAgent(Agent):
    agent_id = AgentId.CLN
    output_model = CloneCheckOutput
    tool_names = (
        "official_contacts_for",
        "reverse_contact_lookup",
        "compare_domain",
        "analyse_phone",
        "analyse_payment",
    )

    def prompt_parts(self, env: AgentEnv, task: Task) -> tuple[str, ...]:
        return (
            "_shared",
            "clone_check",
            "_contact_guide",
            "_conversation",
            render_rule_cards(self.rule_card_text(env, "CLONE-")),
        )

    def spec(self, env: AgentEnv, task: Task) -> AgentSpec:
        spec = super().spec(env, task)
        if task.options.share:
            return spec
        return replace(spec, tool_names=(*spec.tool_names, *ALONE_TOOLS))

    def case_data(self, env: AgentEnv, task: Task) -> dict[str, Any]:
        view = clone_view(env.board, task.options)
        if not task.options.share:
            view["working_alone"] = WORKING_ALONE
        return view

    def task_text(self, task: Task) -> str:
        if task.kind == "respond":
            return "Answer every message in your inbox. Report only what is new."
        return "Compare the offer's contact and payment details with the official record."

    def check_output(self, env: AgentEnv, task: Task, output: CloneCheckOutput) -> list[str]:
        assert env.board.case is not None
        points = env.board.case.contact_points
        known = {point.cp_id for point in points}
        problems = [f"unknown cp_id {c.cp_id!r}" for c in output.contacts if c.cp_id not in known]
        if task.kind == "initial":
            assessed = {contact.cp_id for contact in output.contacts}
            problems += [
                f"no assessment for deciding contact point {point.cp_id}"
                for point in points
                if point.role is ContactRole.DECIDING and point.cp_id not in assessed
            ]
        return problems

    def apply(self, env: AgentEnv, task: Task, output: CloneCheckOutput) -> list[str]:
        board, r = env.board, task.round
        posted: list[str] = []
        for contact in output.contacts:
            official = [contact.official_evidence_id] if contact.official_evidence_id else []
            finding = board.post_finding(
                self.agent_id,
                ContactAssessment(
                    cp_id=contact.cp_id,
                    status=contact.status,
                    official_evidence_id=contact.official_evidence_id,
                ),
                evidence_ids=[*official, *contact.evidence_ids],
                rationale=clip_words(contact.rationale),
                round=r,
            )
            posted.append(finding.finding_id)
        payment = _as_the_tool_found(env, output.payment)
        says_something = payment is not None and (
            payment.beneficiary_matches is not None
            or payment.wallet_requested
            or payment.iban_country
        )
        if payment is not None and says_something:
            finding = board.post_finding(
                self.agent_id,
                PaymentAssessment(
                    beneficiary_matches=payment.beneficiary_matches,
                    wallet_requested=payment.wallet_requested,
                    iban_country=payment.iban_country,
                ),
                evidence_ids=payment.evidence_ids,
                rationale=clip_words(payment.rationale),
                round=r,
            )
            posted.append(finding.finding_id)
        self.handle_conversation(env, task, output)
        return posted

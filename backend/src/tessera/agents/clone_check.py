"""The Clone-check agent: are the offer's contact details the firm's official ones? (§5.2)"""

from __future__ import annotations

from typing import Any

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.schemas import CloneCheckOutput
from tessera.blackboard.views import clone_view
from tessera.llm.prompts import render_rule_cards
from tessera.protocol.claims import ContactAssessment, PaymentAssessment
from tessera.protocol.common import AgentId, clip_words
from tessera.protocol.contacts import ContactRole


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
            "_conversation",
            render_rule_cards(self.rule_card_text(env, "CLONE-")),
        )

    def case_data(self, env: AgentEnv, task: Task) -> dict[str, Any]:
        return clone_view(env.board, task.options)

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
        if output.payment is not None:
            payment = output.payment
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

"""The Jurisdiction agent: which regulators could be relevant to this offer (§5.2)."""

from __future__ import annotations

from typing import Any

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.schemas import JurisdictionOutput
from tessera.blackboard.views import jurisdiction_view
from tessera.llm.prompts import render_activities, render_rule_cards
from tessera.protocol.claims import (
    ActivityClaim,
    CoverageGap,
    OfferClaim,
    Relevance,
    Targeting,
    ZoneSignal,
)
from tessera.protocol.common import REGULATORS, AgentId, clip_words


class JurisdictionAgent(Agent):
    agent_id = AgentId.JUR
    output_model = JurisdictionOutput

    def prompt_parts(self, env: AgentEnv, task: Task) -> tuple[str, ...]:
        return (
            "_shared",
            "jurisdiction",
            "_jurisdiction_guide",
            "_conversation",
            render_rule_cards(self.rule_card_text(env, "JUR-", "CLONE-")),
            render_activities(env.taxonomy),
        )

    def case_data(self, env: AgentEnv, task: Task) -> dict[str, Any]:
        return jurisdiction_view(env.board, task.options)

    def task_text(self, task: Task) -> str:
        if task.kind == "respond":
            return "Answer every message in your inbox. Do not repeat your earlier findings."
        return "Analyse the offer and return your findings."

    def check_output(self, env: AgentEnv, task: Task, output: JurisdictionOutput) -> list[str]:
        problems: list[str] = []
        codes = {activity.code for activity in env.taxonomy.activities}
        problems += [
            f"unknown activity code {a.code!r}" for a in output.activities if a.code not in codes
        ]
        for item in output.relevance:
            problems += env.unknown_rules(item.rule_ids)
        if task.kind == "initial":
            listed = sorted(item.regulator for item in output.relevance)
            if listed != sorted(REGULATORS):
                problems.append(f"relevance must list each of {', '.join(REGULATORS)} exactly once")
            if output.targets_uae_clients is None:
                problems.append("targets_uae_clients is required")
        return problems

    def apply(self, env: AgentEnv, task: Task, output: JurisdictionOutput) -> list[str]:
        board, r = env.board, task.round
        posted: list[str] = []

        def post(
            assertion: Any, evidence: list[str], rationale: str = "", confidence: Any = "medium"
        ) -> Any:
            finding = board.post_finding(
                self.agent_id,
                assertion,
                evidence_ids=evidence,
                rationale=clip_words(rationale),
                confidence=confidence,
                round=r,
            )
            posted.append(finding.finding_id)
            return finding

        for activity in output.activities:
            post(
                ActivityClaim(code=activity.code),
                env.quote_evidence(activity.quote),
                confidence=activity.confidence,
            )
        for zone in output.zone_signals:
            post(ZoneSignal(zone=zone.zone, basis=zone.basis), env.quote_evidence(zone.quote))
        for claim in output.claims:
            if claim.value.strip():  # a blank value states nothing about the offer
                post(
                    OfferClaim(kind=claim.kind, value=claim.value), env.quote_evidence(claim.quote)
                )
        if output.targets_uae_clients is not None:
            post(Targeting(targets_uae_clients=output.targets_uae_clients), [])
        for item in output.relevance:
            finding = post(
                Relevance(
                    regulator=item.regulator, status=item.status, rule_ids=tuple(item.rule_ids)
                ),
                env.rule_evidence(item.rule_ids),
                item.rationale,
            )
            if (
                item.status in ("primary", "possible")
                and item.regulator not in env.covered_regulators
            ):
                board.post_finding(
                    AgentId.ORC,
                    CoverageGap(
                        regulator=item.regulator, reason="not covered in this phase or mode"
                    ),
                    depends_on=(finding.finding_id,),
                    round=r,
                )
        self.handle_conversation(env, task, output)
        return posted

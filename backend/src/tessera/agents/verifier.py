"""The Verifier's model checks: entailment and contradiction search (§6.8).

The Verifier reads typed claims and the full evidence store, and never the Reconciler's reasoning.
Part 3 adds the deterministic gates G1–G8 and the veto loop. This module provides the model half,
and reports a veto when a claim is unsupported or evidence contradicts the proposal.
"""

from __future__ import annotations

from typing import Any

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.schemas import VerifierOutput
from tessera.blackboard.views import verifier_view
from tessera.llm.prompts import render_rule_cards
from tessera.protocol.common import AgentId
from tessera.protocol.results import ContradictionCheck, EntailmentCheck, VerifierReport


class VerifierAgent(Agent):
    agent_id = AgentId.VER
    output_model = VerifierOutput

    def prompt_parts(self, env: AgentEnv, task: Task) -> tuple[str, ...]:
        return ("_shared", "verifier", render_rule_cards(env.rule_cards.values()))

    def case_data(self, env: AgentEnv, task: Task) -> dict[str, Any]:
        return verifier_view(env.board, env.board.proposals[-1], env.facts_for)

    def task_text(self, task: Task) -> str:
        return (
            "Check every claim against its evidence, then search all the evidence for "
            "contradictions."
        )

    def check_output(self, env: AgentEnv, task: Task, output: VerifierOutput) -> list[str]:
        count = len(env.board.proposals[-1].claims)
        seen = {item.claim_index for item in output.entailment}
        return [f"no entailment verdict for claim {i}" for i in range(count) if i not in seen]

    def apply(self, env: AgentEnv, task: Task, output: VerifierOutput) -> list[str]:
        report = self.report(env, output)
        env.board.post_verifier_report(report)
        return []

    def report(self, env: AgentEnv, output: VerifierOutput) -> VerifierReport:
        proposal = env.board.proposals[-1]
        entailment = tuple(
            EntailmentCheck(
                claim_index=item.claim_index, verdict=item.verdict, rationale=item.rationale
            )
            for item in output.entailment
            if 0 <= item.claim_index < len(proposal.claims)
        )
        contradictions = tuple(
            ContradictionCheck(
                evidence_id=item.evidence_id,
                claim_index=item.claim_index,
                rationale=item.rationale,
            )
            for item in output.contradictions
            if item.evidence_id in env.board.evidence
        )
        reasons = [
            f"claim {check.claim_index} is {check.verdict.replace('_', ' ')}"
            for check in entailment
            if check.verdict == "unsupported"
        ]
        reasons += [
            f"evidence {check.evidence_id} contradicts the proposal" for check in contradictions
        ]
        return VerifierReport(
            proposal_version=proposal.version,
            decision="VETO" if reasons else "APPROVE",
            entailment=entailment,
            contradictions=contradictions,
            veto_reasons=tuple(reasons),
        )

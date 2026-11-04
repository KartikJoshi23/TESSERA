"""The Reconciler: mediates conflicts and writes the proposed result (§6.7).

It owns no facts and cannot create evidence. It has no tools. It works only from findings, and
every resolution must cite a precedence rule, so it cannot overrule evidence by argument.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from typing import Any

from tessera.agents.base import Agent, AgentEnv, Task, send_outgoing
from tessera.agents.schemas import (
    ReconcilerRoundOutput,
    ReconcilerSynthesisOutput,
    ResolutionItem,
)
from tessera.blackboard.views import reconciler_view
from tessera.llm.prompts import render_decision_policy, render_rule_cards
from tessera.llm.runner import AgentSpec
from tessera.protocol.common import AgentId, ResultCode, clip_words
from tessera.protocol.messages import ProtocolViolation
from tessera.protocol.results import ProposedResult, RegulatorCoverage, ResultClaim

_HARD_CONFLICTS = {f"HC{i}" for i in range(1, 7)}
_UNVERIFIED_REASONS = {f"U{i}" for i in range(1, 9)}
_CLAIM_WORDS = 40


class ReconcilerAgent(Agent):
    agent_id = AgentId.REC
    output_model = ReconcilerSynthesisOutput

    def spec(self, env: AgentEnv, task: Task) -> AgentSpec:
        model = (
            ReconcilerRoundOutput if task.kind == "challenge_round" else ReconcilerSynthesisOutput
        )
        return replace(super().spec(env, task), output_model=model)

    def prompt_parts(self, env: AgentEnv, task: Task) -> tuple[str, ...]:
        role = "reconciler_round" if task.kind == "challenge_round" else "reconciler_synthesis"
        return (
            "_shared",
            role,
            render_rule_cards(env.rule_cards.values()),
            render_decision_policy(env.decision),
        )

    def case_data(self, env: AgentEnv, task: Task) -> dict[str, Any]:
        return reconciler_view(env.board, env.facts_for)

    def task_text(self, task: Task) -> str:
        if task.kind == "challenge_round":
            return "Deal with every open conflict: resolve it now, or ask the agent concerned."
        return "Resolve what is still open, then write the proposed result."

    def check_output(self, env: AgentEnv, task: Task, output: Any) -> list[str]:
        problems = [
            f"unknown precedence rule {item.precedence_rule!r}"
            for item in output.resolutions
            if item.precedence_rule not in {f"P{i}" for i in range(1, 8)}
        ]
        if isinstance(output, ReconcilerSynthesisOutput):
            problems += self._check_synthesis(env, output)
        return problems

    def _check_synthesis(self, env: AgentEnv, output: ReconcilerSynthesisOutput) -> list[str]:
        problems = [
            f"unknown hard conflict {c!r}"
            for c in output.hard_conflicts
            if c not in _HARD_CONFLICTS
        ]
        problems += [
            f"unknown reason {u!r}"
            for u in output.unverified_reasons
            if u not in _UNVERIFIED_REASONS
        ]
        if output.result is ResultCode.CONFLICTS and not output.hard_conflicts:
            problems.append("CONFLICTS needs at least one hard conflict")
        if output.result is ResultCode.UNVERIFIED and not output.unverified_reasons:
            problems.append("UNVERIFIED needs at least one reason")
        problems += [
            f"unknown finding {claim.finding_id!r}"
            for claim in output.claims
            if claim.finding_id not in env.board.findings
        ]
        if not output.explanation.strip():
            problems.append("explanation is required")
        return problems

    def _resolve(self, env: AgentEnv, task: Task, item: ResolutionItem) -> None:
        board = env.board
        if item.conflict_id not in board.conflicts:
            board.log_rejection("unknown_conflict", item.conflict_id, self.agent_id)
            return
        with suppress(ProtocolViolation):  # the blackboard has logged the rejection
            board.resolve_conflict(
                item.conflict_id,
                outcome=item.outcome,
                precedence_rule=item.precedence_rule,
                winning_finding_ids=item.winning_finding_ids,
                evidence_ids=item.evidence_ids,
                rationale=clip_words(item.rationale),
                round=task.round,
            )

    def apply(self, env: AgentEnv, task: Task, output: Any) -> list[str]:
        for resolution in output.resolutions:
            self._resolve(env, task, resolution)
        if isinstance(output, ReconcilerRoundOutput):
            for conflict in output.new_conflicts:
                env.board.add_conflict(
                    conflict.type,
                    conflict.finding_ids,
                    detected_by="REC",
                    summary=clip_words(conflict.summary),
                )
            for challenge in output.challenges:
                send_outgoing(env, self.agent_id, challenge, task.round)
            return []
        env.board.post_proposal(self._proposal(env, task, output))
        return []

    def _proposal(
        self, env: AgentEnv, task: Task, output: ReconcilerSynthesisOutput
    ) -> ProposedResult:
        board = env.board
        claims = []
        for item in output.claims:
            finding = board.findings[item.finding_id]
            if not finding.is_live:
                board.log_rejection("claim_on_dead_finding", item.finding_id, self.agent_id)
                continue
            claims.append(
                ResultClaim(
                    finding_id=finding.finding_id,
                    assertion=finding.assertion,
                    text=clip_words(item.text, _CLAIM_WORDS),
                    evidence_ids=finding.evidence_ids,
                )
            )
        return ProposedResult(
            version=len(board.proposals) + 1,
            author=self.agent_id,
            result=output.result,
            hard_conflicts=tuple(output.hard_conflicts),
            unverified_reasons=tuple(output.unverified_reasons),
            claims=tuple(claims),
            regulators=tuple(
                RegulatorCoverage(
                    regulator=item.regulator,
                    relevance=item.status,
                    checked=item.regulator in env.covered_regulators,
                    rationale=clip_words(item.rationale),
                )
                for item in output.relevant_regulators
            ),
            explanation=output.explanation.strip(),
            round=task.round,
        )

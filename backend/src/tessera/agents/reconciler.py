"""The Reconciler: mediates conflicts and writes the proposed result (§6.7).

It owns no facts and cannot create evidence. It has no tools. It works only from findings, and
every resolution must cite a precedence rule, so it cannot overrule evidence by argument.
"""

from __future__ import annotations

# A finding's assertion is a union. Findings are picked by type first, so attributes are safe.
# mypy: disable-error-code="union-attr"
from contextlib import suppress
from dataclasses import replace
from typing import Any

from tessera.agents.base import Agent, AgentEnv, Task, send_outgoing
from tessera.agents.schemas import (
    ReconcilerRoundOutput,
    ReconcilerSynthesisOutput,
    RelevantRegulatorItem,
    ResolutionItem,
)
from tessera.blackboard.views import reconciler_view
from tessera.llm.prompts import render_decision_policy, render_rule_cards
from tessera.llm.runner import AgentSpec
from tessera.protocol.claims import needs_evidence
from tessera.protocol.common import AgentId, ResultCode, clip_words
from tessera.protocol.messages import ProtocolViolation
from tessera.protocol.results import ProposedResult, RegulatorCoverage, ResultClaim

_HARD_CONFLICTS = {f"HC{i}" for i in range(1, 7)}
_CLAIM_WORDS = 40
#: Tasks that use the conversational prompt and output, and so write no proposal.
_ROUND_TASKS = ("challenge_round", "remediate")


class ReconcilerAgent(Agent):
    agent_id = AgentId.REC
    output_model = ReconcilerSynthesisOutput

    def spec(self, env: AgentEnv, task: Task) -> AgentSpec:
        model = ReconcilerRoundOutput if task.kind in _ROUND_TASKS else ReconcilerSynthesisOutput
        return replace(super().spec(env, task), output_model=model)

    def prompt_parts(self, env: AgentEnv, task: Task) -> tuple[str, ...]:
        roles = (
            ("reconciler_round",)
            if task.kind in _ROUND_TASKS
            else ("reconciler_synthesis", "_decision_guide")
        )
        return (
            "_shared",
            *roles,
            render_rule_cards(env.rule_cards.values()),
            render_decision_policy(env.decision),
        )

    def case_data(self, env: AgentEnv, task: Task) -> dict[str, Any]:
        return reconciler_view(env.board, env.facts_for)

    def task_text(self, task: Task) -> str:
        if task.kind == "challenge_round":
            return "Deal with every open conflict: resolve it now, or ask the agent concerned."
        if task.kind == "remediate":
            return (
                "The Verifier vetoed the proposal: read the VETO in `messages`. If fixing it needs "
                "a lookup or a correction from an agent, ask now. Otherwise return empty lists."
            )
        if task.revision:
            return (
                "The Verifier vetoed the proposal: read the VETO in `messages`. Fix every reason "
                "it gives, then write the proposed result again."
            )
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
        reasons = {rule.id for rule in env.decision.unverified_reasons}
        problems += [f"unknown reason {u!r}" for u in output.unverified_reasons if u not in reasons]
        if output.result is ResultCode.CONFLICTS and not output.hard_conflicts:
            problems.append("CONFLICTS needs at least one hard conflict")
        if output.result is ResultCode.UNVERIFIED and not output.unverified_reasons:
            problems.append("UNVERIFIED needs at least one reason")
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

    def _coverage(
        self, env: AgentEnv, output: ReconcilerSynthesisOutput
    ) -> tuple[RegulatorCoverage, ...]:
        """What was and was not checked. This is known here, so it does not rest on a model."""
        listed = {item.regulator: item for item in output.relevant_regulators}
        opinions = {
            f.assertion.regulator: f.assertion.status
            for f in env.board.live_findings("relevance")
            if f.assertion.status in ("primary", "possible")
        }
        for regulator, status in opinions.items():
            if regulator not in listed:
                listed[regulator] = RelevantRegulatorItem(regulator=regulator, status=status)
        return tuple(
            RegulatorCoverage(
                regulator=item.regulator,
                relevance=item.status,
                checked=self._was_checked(env, item.regulator),
                rationale=clip_words(item.rationale),
            )
            for item in listed.values()
        )

    @staticmethod
    def _was_checked(env: AgentEnv, regulator: str) -> bool:
        """True only if the regulator is covered and its check really ran."""
        board = env.board
        gap = any(
            f.assertion.regulator == regulator and f.assertion.scope == "regulator"
            for f in board.live_findings("coverage_gap")
        )
        failed = any(failure["agent"] == regulator for failure in board.failures)
        return regulator in env.covered_regulators and not gap and not failed

    def _proposal(
        self, env: AgentEnv, task: Task, output: ReconcilerSynthesisOutput
    ) -> ProposedResult:
        board = env.board
        claims = []
        for item in output.claims:
            finding = board.findings.get(item.finding_id)
            if finding is None:
                # A slip in one claim should not lose the case. The gates check what remains.
                board.log_rejection("claim_on_unknown_finding", item.finding_id, self.agent_id)
                continue
            if not finding.is_live:
                board.log_rejection("claim_on_dead_finding", item.finding_id, self.agent_id)
                continue
            # The Verifier would rightly call this unsupported. Coverage is reported separately.
            if not finding.evidence_ids and not needs_evidence(finding.assertion):
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
            regulators=self._coverage(env, output),
            explanation=output.explanation.strip(),
            round=task.round,
        )

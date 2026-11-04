"""Regulator agents: one behaviour, specialised by rule card and tools (§5.2).

Each states its own relevance opinion independently of the Jurisdiction agent, so disagreements
come to the surface instead of being hidden.
"""

from __future__ import annotations

from typing import Any

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.schemas import RegulatorOutput
from tessera.blackboard.views import regulator_view
from tessera.llm.prompts import render_activities, render_rule_cards
from tessera.protocol.claims import (
    AlertHit,
    CoverageGap,
    LicenceScope,
    LicenceStatus,
    RegisterMatch,
    RegisterNoMatch,
    Relevance,
)
from tessera.protocol.common import AgentId, Regulator, clip_words
from tessera.protocol.evidence import REGISTER_SOURCES


class RegulatorAgent(Agent):
    output_model = RegulatorOutput

    def __init__(
        self,
        agent_id: AgentId,
        regulator: Regulator,
        prompt: str,
        tools: tuple[str, ...],
        scope_prefix: str,
    ) -> None:
        self.agent_id = agent_id
        self.regulator = regulator
        self.prompt = prompt
        self.tool_names = tools
        self.scope_prefix = scope_prefix

    def prompt_parts(self, env: AgentEnv, task: Task) -> tuple[str, ...]:
        return (
            "_shared",
            "regulator",
            self.prompt,
            "_conversation",
            render_rule_cards(self.rule_card_text(env, "JUR-", self.scope_prefix, "CLONE-")),
            render_activities(env.taxonomy),
        )

    def case_data(self, env: AgentEnv, task: Task) -> dict[str, Any]:
        return regulator_view(env.board, self.agent_id, task.options)

    def task_text(self, task: Task) -> str:
        if task.kind == "respond":
            return "Answer every message in your inbox. Report only what is new."
        return f"Check {self.regulator}'s records for this offer and return your findings."

    def check_output(self, env: AgentEnv, task: Task, output: RegulatorOutput) -> list[str]:
        problems: list[str] = []
        if task.kind == "initial" and output.relevance is None:
            problems.append("relevance is required")
        if output.relevance is not None:
            problems += env.unknown_rules(output.relevance.rule_ids)
        problems += env.unknown_rules(item.rule_id for item in output.scope)
        codes = {activity.code for activity in env.taxonomy.activities}
        problems += [
            f"unknown activity code {item.activity!r}"
            for item in output.scope
            if item.activity not in codes
        ]
        return problems

    def apply(self, env: AgentEnv, task: Task, output: RegulatorOutput) -> list[str]:
        board, r, me = env.board, task.round, self.agent_id
        posted: list[str] = []

        def post(assertion: Any, evidence: Any, rationale: str = "", depends_on: Any = ()) -> str:
            finding = board.post_finding(
                me,
                assertion,
                evidence_ids=list(evidence),
                rationale=clip_words(rationale),
                depends_on=depends_on,
                round=r,
            )
            posted.append(finding.finding_id)
            return finding.finding_id

        if output.relevance is not None:
            own = output.relevance
            post(
                Relevance(
                    regulator=self.regulator, status=own.status, rule_ids=tuple(own.rule_ids)
                ),
                env.rule_evidence(own.rule_ids),
                own.rationale,
            )
        for item in output.register_matches:
            match_id = post(
                RegisterMatch(
                    regulator=self.regulator,
                    entity_evidence_id=item.evidence_id,
                    match_type=item.match_type,
                    second_identifier=item.second_identifier,
                ),
                [item.evidence_id],
                item.rationale,
            )
            post(
                LicenceStatus(
                    regulator=self.regulator,
                    entity_evidence_id=item.evidence_id,
                    status=item.status,
                ),
                [item.evidence_id],
                depends_on=(match_id,),
            )
        for evidence_id in output.no_match_evidence_ids:
            # A no-match on a warnings list stays on the board as evidence, but says nothing
            # about the register. An invented ID is kept, so that conflict C6 can flag it.
            record = board.evidence.get(evidence_id)
            if record is None or record.source_id in REGISTER_SOURCES:
                post(RegisterNoMatch(regulator=self.regulator), [evidence_id])
        for scope in output.scope:
            rule_ids = [scope.rule_id] if scope.rule_id else []
            post(
                LicenceScope(
                    regulator=self.regulator,
                    entity_evidence_id=scope.entity_evidence_id,
                    activity=scope.activity,
                    covered=scope.covered,
                    rule_id=scope.rule_id,
                ),
                [scope.entity_evidence_id, *env.rule_evidence(rule_ids)],
                scope.rationale,
            )
        for alert in output.alerts:
            record = board.evidence.get(alert.evidence_id)
            post(
                AlertHit(
                    source_id=record.source_id if record else "unknown",
                    alert_evidence_id=alert.evidence_id,
                    about=alert.about,
                    matched_on=alert.matched_on,
                ),
                [alert.evidence_id],
                alert.rationale,
            )
        for note in output.not_checked:
            post(CoverageGap(regulator=self.regulator, reason=note, scope="field"), [])
        if task.kind == "initial" and not self._records_consulted(env):
            board.post_finding(
                AgentId.ORC,
                CoverageGap(regulator=self.regulator, reason="not every list was consulted"),
                round=r,
            )
        self.handle_conversation(env, task, output)
        return posted

    def _records_consulted(self, env: AgentEnv) -> bool:
        """Deterministic: did every source of this regulator actually produce evidence?

        A lookup always mints evidence, even for no match, so a source with none was not checked.
        One skipped list is enough to count: a warning nobody read cannot block a result.
        """
        sources = {
            source_id
            for source_id, policy in env.ctx.sources.sources.items()
            if policy.regulator == self.regulator and policy.enabled
        }
        return sources <= {record.source_id for record in env.board.evidence.values()}


def build_regulator_agents() -> dict[AgentId, RegulatorAgent]:
    return {
        AgentId.CMA: RegulatorAgent(
            AgentId.CMA,
            "CMA",
            "regulator_cma",
            ("cma_register_lookup", "cma_warnings_lookup"),
            "SCOPE-CMA-",
        ),
        AgentId.DFSA: RegulatorAgent(
            AgentId.DFSA, "DFSA", "regulator_dfsa", ("dfsa_facts_lookup",), "SCOPE-DFSA-"
        ),
        AgentId.VARA: RegulatorAgent(
            AgentId.VARA,
            "VARA",
            "regulator_vara",
            ("vara_register_lookup", "vara_unlicensed_lookup"),
            "SCOPE-VARA-",
        ),
    }

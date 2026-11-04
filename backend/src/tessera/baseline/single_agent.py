"""The single-agent baselines (§10.2): one agent with every tool and all the knowledge.

Only the orchestration differs from the crew. The agent uses the same runner, tools, rule cards,
policies, gates and report. It does everything in one turn and returns one object, and its work is
posted through the same code the crew's agents use, so its findings are the same typed findings and
the Verifier checks them in the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.clone_check import CloneCheckAgent
from tessera.agents.jurisdiction import JurisdictionAgent
from tessera.agents.reconciler import ReconcilerAgent
from tessera.agents.regulators import build_regulator_agents
from tessera.agents.schemas import (
    CloneCheckOutput,
    JurisdictionOutput,
    ReconcilerSynthesisOutput,
    RegulatorOutput,
    RelevantRegulatorItem,
    SingleAgentOutput,
    SynthesisClaimItem,
)
from tessera.agents.toolbelt import TOOLS
from tessera.agents.verifier import VerifierAgent
from tessera.blackboard.views import contact_views, evidence_view, finding_view
from tessera.llm.prompts import render_activities, render_decision_policy, render_rule_cards
from tessera.orchestration.decision import derive_decision
from tessera.orchestration.verification import verify_latest
from tessera.protocol.claims import DECISIVE_TYPES, describe, needs_evidence
from tessera.protocol.common import AgentId
from tessera.protocol.results import FinalResult
from tessera.reporting.report import compose_final


@dataclass(frozen=True)
class SingleConfig:
    """What separates the single-agent conditions from one another."""

    verifier: bool = False
    max_remediations: int = 0


class _Jurisdiction(JurisdictionAgent):
    agent_id = AgentId.SA


class _CloneCheck(CloneCheckAgent):
    agent_id = AgentId.SA


class _Reconciler(ReconcilerAgent):
    agent_id = AgentId.SA


class SingleAgent(Agent):
    agent_id = AgentId.SA
    output_model = SingleAgentOutput
    tool_names = tuple(TOOLS)

    def __init__(self) -> None:
        self.jurisdiction = _Jurisdiction()
        self.regulators = {
            agent.regulator: replace_author(agent) for agent in build_regulator_agents().values()
        }
        self.clone_check = _CloneCheck()
        self.reconciler = _Reconciler()

    def prompt_parts(self, env: AgentEnv, task: Task) -> tuple[str, ...]:
        return (
            "_shared",
            "single_agent",
            "_jurisdiction_guide",
            "_regulator_guide",
            "regulator_cma",
            "regulator_dfsa",
            "regulator_vara",
            "_contact_guide",
            "_decision_guide",
            render_rule_cards(env.rule_cards.values()),
            render_activities(env.taxonomy),
            render_decision_policy(env.decision),
        )

    def case_data(self, env: AgentEnv, task: Task) -> dict[str, Any]:
        board = env.board
        data: dict[str, Any] = {"contact_points": contact_views(board)}
        if task.revision:
            data["veto_reasons"] = list(board.verifier_reports[-1].veto_reasons)
            data["your_findings"] = [finding_view(f) for f in board.live_findings()]
            data["evidence"] = [evidence_view(e, env.facts_for) for e in board.evidence.values()]
        return data

    def task_text(self, task: Task) -> str:
        if task.revision:
            return (
                "A Verifier vetoed your result: see `veto_reasons`. Fix every reason, and return "
                "the whole object again. It replaces your earlier findings."
            )
        return "Do every step, then return the one JSON object."

    # ------------------------------------------------------------------ parts of the output

    @staticmethod
    def _jurisdiction_part(output: SingleAgentOutput) -> JurisdictionOutput:
        return JurisdictionOutput(
            activities=output.activities,
            zone_signals=output.zone_signals,
            claims=output.claims,
            targets_uae_clients=output.targets_uae_clients,
            relevance=output.relevance,
        )

    @staticmethod
    def _regulator_part(output: SingleAgentOutput, regulator: str) -> RegulatorOutput:
        section = next((s for s in output.regulators if s.regulator == regulator), None)
        return (
            RegulatorOutput(**section.model_dump(exclude={"regulator"}))
            if section
            else RegulatorOutput()
        )

    @staticmethod
    def _synthesis_part(
        output: SingleAgentOutput, claims: list[SynthesisClaimItem]
    ) -> ReconcilerSynthesisOutput:
        return ReconcilerSynthesisOutput(
            relevant_regulators=[
                RelevantRegulatorItem(regulator=item.regulator, status=item.status)
                for item in output.relevance
                if item.status in ("primary", "possible")
            ],
            result=output.result,
            hard_conflicts=output.hard_conflicts,
            unverified_reasons=output.unverified_reasons,
            claims=claims,
            explanation=output.explanation,
        )

    def check_output(self, env: AgentEnv, task: Task, output: SingleAgentOutput) -> list[str]:
        problems = self.jurisdiction.check_output(env, task, self._jurisdiction_part(output))
        # The agent states relevance once, for every regulator, rather than per section.
        partial = replace(task, kind="respond")
        for regulator, agent in self.regulators.items():
            problems += agent.check_output(env, partial, self._regulator_part(output, regulator))
        problems += self.clone_check.check_output(
            env, task, CloneCheckOutput(contacts=output.contacts, payment=output.payment)
        )
        problems += self.reconciler._check_synthesis(env, self._synthesis_part(output, []))
        return problems

    def apply(self, env: AgentEnv, task: Task, output: SingleAgentOutput) -> list[str]:
        board = env.board
        if task.revision:
            board.supersede_findings(AgentId.SA, round=task.round)
        posted = self.jurisdiction.apply(env, task, self._jurisdiction_part(output))
        for regulator, agent in self.regulators.items():
            posted += agent.apply(env, task, self._regulator_part(output, regulator))
        posted += self.clone_check.apply(
            env, task, CloneCheckOutput(contacts=output.contacts, payment=output.payment)
        )
        claims = [
            SynthesisClaimItem(
                finding_id=finding.finding_id,
                text=finding.rationale or describe(finding.assertion),
            )
            for finding in board.live_findings()
            if finding.author is AgentId.SA
            and finding.assertion.type in DECISIVE_TYPES
            and needs_evidence(finding.assertion)
        ]
        board.post_proposal(
            self.reconciler._proposal(env, task, self._synthesis_part(output, claims))
        )
        return posted


def replace_author(agent: Any) -> Any:
    """The same regulator behaviour, with its findings posted by the single agent."""
    agent.agent_id = AgentId.SA
    return agent


async def run_single_agent(
    env: AgentEnv,
    config: SingleConfig,
    *,
    today: date,
    agent: Agent | None = None,
    verifier: Agent | None = None,
) -> FinalResult:
    """Run one offer through one agent, with the Verifier if this condition has it."""
    board = env.board
    actor = agent or SingleAgent()
    checker = verifier or VerifierAgent()
    board.record("round.started", AgentId.ORC, {"round": 0, "phase": "single_agent"})
    await actor.activate(env, Task("initial", round=0))
    number, remediations = 1, 0
    if config.verifier and board.proposals:
        board.record("round.started", AgentId.ORC, {"round": number, "phase": "verify"})
        await verify_latest(env, checker, number=number, today=today)
        while board.verifier_reports[-1].decision == "VETO" and (
            remediations < config.max_remediations
        ):
            remediations += 1
            number += 1
            board.record("round.started", AgentId.ORC, {"round": number, "phase": "remediate"})
            version = board.proposals[-1].version
            await actor.activate(env, Task("initial", round=number, revision=True))
            if board.proposals[-1].version == version:
                break
            number += 1
            board.record("round.started", AgentId.ORC, {"round": number, "phase": "verify"})
            await verify_latest(env, checker, number=number, today=today)
    veto = bool(board.verifier_reports) and board.verifier_reports[-1].decision == "VETO"
    decision = derive_decision(env, today=today, veto_standing=veto)
    return board.finalize(
        compose_final(
            env,
            decision,
            verifier_on=config.verifier,
            detail={"challenge_rounds": 0, "remediations": remediations},
        )
    )

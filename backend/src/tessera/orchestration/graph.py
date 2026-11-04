"""The crew's control flow, as a LangGraph state graph (§6.5).

Who runs when depends only on the blackboard, and every loop has a hard limit, so every case ends in
a report. LangGraph provides the control flow only. The event log stays the single record of a
case, so the graph's own state is just a few counters, and it holds nothing restricted.

Cases are not checkpointed mid-way. A node's model calls are not safe to repeat, so resuming inside
a case could post findings twice. A run instead restarts any case it did not finish.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.crew import build_crew
from tessera.agents.verifier import post_report
from tessera.errors import PolicyError
from tessera.llm.runner import TurnResult
from tessera.orchestration.conditions import CrewConfig, config_for
from tessera.orchestration.decision import DecisionEngine, PolicyDecision, derive_decision
from tessera.orchestration.detector import run_detector
from tessera.orchestration.gates import is_under_call, run_gates
from tessera.protocol.common import REGULATOR_AGENTS, AgentId
from tessera.protocol.results import FinalResult, VerifierReport
from tessera.reporting.report import compose_final

# Graph state is counters only, but tracing would still send it to a third party.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

#: Every loop is bounded, so this only guards against a mistake in the graph itself.
_RECURSION_LIMIT = 60
#: Wording and coverage can be fixed from what is already on the board.
_NEEDS_NO_LOOKUP = frozenset({"G5", "G7"})
_ROUND_REGULATORS = 1
_ROUND_CLONE = 2
_ROUND_CHALLENGES = 3


class CrewState(TypedDict):
    round: int
    challenge_rounds: int
    remediations: int
    #: Whether the Reconciler's last challenge round did anything.
    progress: bool


class CrewRun:
    """One case's nodes and routing. All case state lives on the blackboard."""

    def __init__(
        self, env: AgentEnv, crew: dict[AgentId, Agent], config: CrewConfig, today: date
    ) -> None:
        self.env = env
        self.board = env.board
        self.crew = crew
        self.config = config
        self.today = today

    # ------------------------------------------------------------------ helpers

    def _round(self, number: int, phase: str) -> None:
        self.board.record("round.started", AgentId.ORC, {"round": number, "phase": phase})

    def _task(self, kind: Any, number: int, **fields: Any) -> Task:
        return Task(kind, round=number, options=self.config.options, **fields)

    async def _turns(self, *turns: tuple[AgentId, Task]) -> list[TurnResult]:
        return list(
            await asyncio.gather(*(self.crew[agent].activate(self.env, t) for agent, t in turns))
        )

    def _addressed(self, exclude: tuple[AgentId, ...] = ()) -> list[AgentId]:
        """Agents with unanswered messages, in a fixed order, so scheduling is deterministic."""
        return [
            agent
            for agent in self.crew
            if agent not in exclude
            and agent not in (AgentId.REC, AgentId.VER)
            and self.board.inbox(agent)
        ]

    def decide(self, *, veto_standing: bool = False) -> PolicyDecision:
        return derive_decision(self.env, today=self.today, veto_standing=veto_standing)

    # ------------------------------------------------------------------ nodes

    async def jurisdiction(self, state: CrewState) -> dict[str, Any]:
        self._round(0, "R0")
        await self._turns((AgentId.JUR, self._task("initial", 0)))
        return {"round": 0}

    async def regulators(self, state: CrewState) -> dict[str, Any]:
        self._round(_ROUND_REGULATORS, "R1")
        task = self._task("initial", _ROUND_REGULATORS)
        await self._turns(*((agent, task) for agent in REGULATOR_AGENTS))
        return {"round": _ROUND_REGULATORS}

    async def clone_check(self, state: CrewState) -> dict[str, Any]:
        """Clone-check, plus any agent addressed in the round before (§6.5, R2)."""
        self._round(_ROUND_CLONE, "R2")
        respond = self._task("respond", _ROUND_CLONE)
        await self._turns(
            (AgentId.CLN, self._task("initial", _ROUND_CLONE)),
            *((agent, respond) for agent in self._addressed(exclude=(AgentId.CLN,))),
        )
        return {"round": _ROUND_CLONE}

    def detect(self, state: CrewState) -> dict[str, Any]:
        run_detector(self.env, DecisionEngine(self.env, self.today), round=state["round"])
        return {}

    async def reconcile(self, state: CrewState) -> dict[str, Any]:
        number = _ROUND_CHALLENGES + state["challenge_rounds"]
        self._round(number, "reconcile")
        before = (len(self.board.resolutions), len(self.board.messages))
        await self._turns((AgentId.REC, self._task("challenge_round", number)))
        return {
            "round": number,
            "challenge_rounds": state["challenge_rounds"] + 1,
            "progress": before != (len(self.board.resolutions), len(self.board.messages)),
        }

    async def respond(self, state: CrewState) -> dict[str, Any]:
        task = self._task("respond", state["round"])
        await self._turns(*((agent, task) for agent in self._addressed()))
        return {}

    async def synthesis(self, state: CrewState) -> dict[str, Any]:
        number = state["round"] + 1
        self._round(number, "synthesis")
        await self._turns((AgentId.REC, self._task("synthesis", number)))
        return {"round": number}

    async def verify(self, state: CrewState) -> dict[str, Any]:
        number = state["round"] + 1
        self._round(number, "verify")
        proposal = self.board.proposals[-1]
        decision = self.decide()
        self.board.record(
            "policy.derived",
            AgentId.ORC,
            {"proposal_version": proposal.version, **decision.summary()},
        )
        gates = run_gates(self.env, proposal, decision)
        under_call = is_under_call(proposal, decision)
        failed = [gate for gate in gates if not gate.passed]
        if failed:
            post_report(
                self.env,
                VerifierReport(
                    proposal_version=proposal.version,
                    decision="VETO",
                    gates=gates,
                    veto_reasons=tuple(f"{gate.gate}: {gate.detail}" for gate in failed),
                    under_call=under_call,
                ),
                number,
            )
            return {"round": number}
        task = self._task("verify", number, gates=gates, under_call=under_call)
        turn = (await self._turns((AgentId.VER, task)))[0]
        if not turn.ok:
            post_report(
                self.env,
                VerifierReport(
                    proposal_version=proposal.version,
                    decision="VETO",
                    gates=gates,
                    veto_reasons=("the Verifier could not finish its checks",),
                    under_call=under_call,
                ),
                number,
            )
        return {"round": number}

    async def remediate(self, state: CrewState) -> dict[str, Any]:
        number = state["round"] + 1
        self._round(number, "remediate")
        failed = {gate.gate for gate in self.board.verifier_reports[-1].gates if not gate.passed}
        if self.config.challenges and not (failed and failed <= _NEEDS_NO_LOOKUP):
            await self._turns((AgentId.REC, self._task("remediate", number)))
            respond = self._task("respond", number)
            await self._turns(*((agent, respond) for agent in self._addressed()))
        await self._turns((AgentId.REC, self._task("synthesis", number, revision=True)))
        return {"round": number, "remediations": state["remediations"] + 1}

    def report(self, state: CrewState) -> dict[str, Any]:
        self.board.finalize(
            compose_final(
                self.env,
                self.decide(veto_standing=self._veto_stands()),
                verifier_on=self.config.verifier,
                detail={
                    "challenge_rounds": state["challenge_rounds"],
                    "remediations": state["remediations"],
                },
            )
        )
        return {}

    # ------------------------------------------------------------------ routing

    def _veto_stands(self) -> bool:
        reports = self.board.verifier_reports
        return bool(reports) and reports[-1].decision == "VETO"

    def after_detect(self, state: CrewState) -> str:
        may_continue = (
            self.config.challenges
            and state["challenge_rounds"] < self.config.max_challenge_rounds
            and (state["challenge_rounds"] == 0 or state["progress"])
        )
        return "reconcile" if may_continue and self.board.open_conflicts() else "synthesis"

    def after_reconcile(self, state: CrewState) -> str:
        return "respond" if self._addressed() else "detect"

    def after_synthesis(self, state: CrewState) -> str:
        return "verify" if self.config.verifier and self.board.proposals else "report"

    def after_verify(self, state: CrewState) -> str:
        may_retry = state["remediations"] < self.config.max_remediations
        return "remediate" if self._veto_stands() and may_retry else "report"

    def after_remediate(self, state: CrewState) -> str:
        """Without a new proposal there is nothing new to verify, so the veto stands."""
        reports = self.board.verifier_reports
        fresh = self.board.proposals[-1].version > reports[-1].proposal_version
        return "verify" if fresh else "report"


def build_graph(run: CrewRun) -> Any:
    builder = StateGraph(CrewState)
    for name in (
        "jurisdiction",
        "regulators",
        "clone_check",
        "detect",
        "reconcile",
        "respond",
        "synthesis",
        "verify",
        "remediate",
        "report",
    ):
        builder.add_node(name, getattr(run, name))
    builder.add_edge(START, "jurisdiction")
    builder.add_edge("jurisdiction", "regulators")
    builder.add_edge("regulators", "clone_check")
    builder.add_edge("clone_check", "detect")
    builder.add_conditional_edges(
        "detect", run.after_detect, {"reconcile": "reconcile", "synthesis": "synthesis"}
    )
    builder.add_conditional_edges(
        "reconcile", run.after_reconcile, {"respond": "respond", "detect": "detect"}
    )
    builder.add_edge("respond", "detect")
    builder.add_conditional_edges(
        "synthesis", run.after_synthesis, {"verify": "verify", "report": "report"}
    )
    builder.add_conditional_edges(
        "verify", run.after_verify, {"remediate": "remediate", "report": "report"}
    )
    builder.add_conditional_edges(
        "remediate", run.after_remediate, {"verify": "verify", "report": "report"}
    )
    builder.add_edge("report", END)
    return builder.compile()


async def run_crew(
    env: AgentEnv,
    *,
    crew: dict[AgentId, Agent] | None = None,
    config: CrewConfig | None = None,
    today: date | None = None,
) -> FinalResult:
    """Run a case to its final result. ``today`` decides whether snapshots count as stale."""
    assert env.board.case is not None
    run = CrewRun(
        env,
        crew or build_crew(),
        config or config_for(env.board.case.condition),
        today or date.today(),
    )
    start: CrewState = {"round": 0, "challenge_rounds": 0, "remediations": 0, "progress": False}
    await build_graph(run).ainvoke(start, {"recursion_limit": _RECURSION_LIMIT})
    if env.board.final is None:
        raise PolicyError("the crew graph ended without a final result")
    return env.board.final

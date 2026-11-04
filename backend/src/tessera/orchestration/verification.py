"""One Verifier step, shared by the crew and SA-VER, so that both are held to the same gates."""

from __future__ import annotations

from datetime import date

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.verifier import post_report
from tessera.blackboard.views import SHARED, ViewOptions
from tessera.orchestration.decision import derive_decision
from tessera.orchestration.gates import is_under_call, run_gates
from tessera.protocol.common import AgentId
from tessera.protocol.results import VerifierReport


async def verify_latest(
    env: AgentEnv,
    verifier: Agent,
    *,
    number: int,
    today: date,
    options: ViewOptions = SHARED,
) -> None:
    """Run the gates on the latest proposal, then the model checks if every gate passed."""
    board = env.board
    proposal = board.proposals[-1]
    decision = derive_decision(env, today=today)
    board.record(
        "policy.derived",
        AgentId.ORC,
        {"proposal_version": proposal.version, **decision.summary()},
    )
    gates = run_gates(env, proposal, decision)
    under_call = is_under_call(proposal, decision)
    failed = [gate for gate in gates if not gate.passed]
    if failed:
        post_report(
            env,
            VerifierReport(
                proposal_version=proposal.version,
                decision="VETO",
                gates=gates,
                veto_reasons=tuple(f"{gate.gate}: {gate.detail}" for gate in failed),
                under_call=under_call,
            ),
            number,
        )
        return
    task = Task("verify", round=number, options=options, gates=gates, under_call=under_call)
    turn = await verifier.activate(env, task)
    if not turn.ok:
        post_report(
            env,
            VerifierReport(
                proposal_version=proposal.version,
                decision="VETO",
                gates=gates,
                veto_reasons=("the Verifier could not finish its checks",),
                under_call=under_call,
            ),
            number,
        )

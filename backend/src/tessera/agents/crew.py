"""Assembles the crew and its per-case environment.

:func:`run_sequence` is a simple one-pass driver: every agent runs once, with no challenge rounds.
It is what smoke runs use until Part 3 adds the full orchestration graph.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from tessera.agents.base import Agent, AgentEnv, Task
from tessera.agents.clone_check import CloneCheckAgent
from tessera.agents.jurisdiction import JurisdictionAgent
from tessera.agents.reconciler import ReconcilerAgent
from tessera.agents.regulators import build_regulator_agents
from tessera.agents.toolbelt import ToolBelt
from tessera.agents.verifier import VerifierAgent
from tessera.blackboard.board import Blackboard
from tessera.blackboard.store import EventStore
from tessera.config.settings import Settings
from tessera.data.registry import DataRegistry
from tessera.governance.masking import MaskingGateway
from tessera.governance.policies import UAE_REGULATORS, SourcesPolicy, load_decision_policy
from tessera.governance.synthetic_gate import OfferInput
from tessera.knowledge import load_activity_taxonomy, load_rule_cards
from tessera.llm.client import GuardedLLM
from tessera.llm.config import ModelsPolicy, load_models_policy
from tessera.llm.prompts import PromptLibrary
from tessera.llm.runner import AgentRunner, TurnResult, UsageMeter
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import REGULATOR_AGENTS, AgentId
from tessera.tools import ToolContext


def build_crew() -> dict[AgentId, Agent]:
    return {
        AgentId.JUR: JurisdictionAgent(),
        **build_regulator_agents(),
        AgentId.CLN: CloneCheckAgent(),
        AgentId.REC: ReconcilerAgent(),
        AgentId.VER: VerifierAgent(),
    }


def covered_regulators(sources: SourcesPolicy, settings: Settings) -> frozenset[str]:
    """Regulators with an enabled source whose data this mode may load."""
    return frozenset(
        policy.regulator
        for policy in sources.sources.values()
        if policy.enabled
        and policy.regulator in UAE_REGULATORS
        and (settings.restricted_allowed or not policy.restricted)
    )


def prompt_library(settings: Settings) -> PromptLibrary:
    return PromptLibrary(Path(settings.root) / "backend" / "prompts")


def open_case_env(
    *,
    store: EventStore,
    settings: Settings,
    registry: DataRegistry,
    gateway: MaskingGateway,
    llm: GuardedLLM,
    case_id: str,
    offer: OfferInput,
    condition: SystemCondition = SystemCondition.CREW_SHARE,
    model: str | None = None,
    models: ModelsPolicy | None = None,
) -> AgentEnv:
    """Admit an offer and build everything its agents need. One environment per case."""
    models = models or load_models_policy(settings.policies_dir)
    chosen = model or models.roles["primary"]
    prompts = prompt_library(settings)
    board = Blackboard.open_case(
        store,
        case_id=case_id,
        offer=offer,
        condition=condition,
        mode=settings.mode,
        gateway=gateway,
        config={"model": chosen, "prompt_version": prompts.version},
    )
    ctx = ToolContext.create(case_id, settings, registry)
    belt = ToolBelt(ctx, board)
    runner = AgentRunner(
        llm,
        belt,
        board,
        model=chosen,
        decoding=models.decoding,
        limits=models.limits,
        meter=UsageMeter(max_requests=models.limits.requests_per_case),
        extra_body=models.options_for(chosen),
    )
    return AgentEnv(
        board=board,
        ctx=ctx,
        belt=belt,
        runner=runner,
        prompts=prompts,
        rule_cards=load_rule_cards(settings.knowledge_dir),
        taxonomy=load_activity_taxonomy(settings.knowledge_dir),
        decision=load_decision_policy(settings.policies_dir),
        covered_regulators=covered_regulators(ctx.sources, settings),
    )


async def run_sequence(env: AgentEnv, crew: dict[AgentId, Agent] | None = None) -> list[TurnResult]:
    """One pass through the crew: Jurisdiction, regulators in parallel, Clone-check, Reconciler,
    Verifier. Part 3 replaces this with challenge rounds and the veto loop."""
    agents = crew or build_crew()
    results: list[TurnResult] = [await agents[AgentId.JUR].activate(env, Task("initial", round=0))]
    regulators: list[Any] = [
        agents[agent].activate(env, Task("initial", round=1)) for agent in REGULATOR_AGENTS
    ]
    results += await asyncio.gather(*regulators)
    results.append(await agents[AgentId.CLN].activate(env, Task("initial", round=2)))
    results.append(await agents[AgentId.REC].activate(env, Task("synthesis", round=3)))
    if env.board.proposals:
        results.append(await agents[AgentId.VER].activate(env, Task("verify", round=4)))
    return results


__all__ = [
    "Blackboard",
    "build_crew",
    "covered_regulators",
    "open_case_env",
    "prompt_library",
    "run_sequence",
]

"""Assembles the crew and its per-case environment."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessera.agents.base import Agent, AgentEnv
from tessera.agents.clone_check import CloneCheckAgent
from tessera.agents.jurisdiction import JurisdictionAgent
from tessera.agents.reconciler import ReconcilerAgent
from tessera.agents.regulators import build_regulator_agents
from tessera.agents.toolbelt import TOOLS, ToolBelt
from tessera.agents.verifier import VerifierAgent
from tessera.blackboard.board import Blackboard
from tessera.blackboard.store import EventStore
from tessera.config.settings import Settings
from tessera.data.registry import DataRegistry
from tessera.governance.masking import MaskingGateway
from tessera.governance.policies import (
    UAE_REGULATORS,
    SourcesPolicy,
    load_decision_policy,
    load_language_policy,
    load_sources_policy,
)
from tessera.governance.synthetic_gate import OfferInput
from tessera.knowledge import load_activity_taxonomy, load_rule_cards
from tessera.llm.client import GuardedLLM
from tessera.llm.config import LimitsConfig, ModelsPolicy, load_models_policy
from tessera.llm.prompts import PromptLibrary
from tessera.llm.runner import AgentRunner, UsageMeter
from tessera.llm.types import ChatTransport
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import AgentId
from tessera.protocol.evidence import canonical_json
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


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:16]


def case_config(
    settings: Settings,
    registry: DataRegistry,
    models: ModelsPolicy,
    model: str,
    limits: LimitsConfig,
    prompt_version: str,
) -> dict[str, Any]:
    """Everything a run depends on, recorded on the case (§10.1, the fairness contract)."""
    policies = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(settings.policies_dir.glob("*.yaml"))
        if path.name != "models.yaml"
    }
    rules = load_rule_cards(settings.knowledge_dir)
    snapshots = {
        source_id: manifest.snapshot_id
        for source_id, policy in registry.sources.sources.items()
        if policy.enabled and (registry.restricted_allowed or not policy.restricted)
        if (manifest := registry.table(source_id).manifest) is not None
    }
    return {
        "model": model,
        "prompt_version": prompt_version,
        "decoding": models.decoding.model_dump(),
        "model_options": models.options_for(model),
        "limits": limits.model_dump(),
        "rate_limit": models.rate_limit.model_dump(),
        "policies_sha": _sha(policies),
        "rule_cards_sha": _sha({key: card.model_dump(mode="json") for key, card in rules.items()}),
        "taxonomy_sha": _sha(load_activity_taxonomy(settings.knowledge_dir).model_dump()),
        "tools_sha": _sha(sorted(TOOLS)),
        "snapshots": snapshots,
    }


def open_case_env(
    *,
    store: EventStore,
    settings: Settings,
    registry: DataRegistry,
    gateway: MaskingGateway,
    llm: GuardedLLM,
    case_id: str,
    offer: OfferInput,
    condition: SystemCondition = SystemCondition.CREW_FULL,
    model: str | None = None,
    models: ModelsPolicy | None = None,
) -> AgentEnv:
    """Admit an offer and build everything its agents need. One environment per case."""
    models = models or load_models_policy(settings.policies_dir)
    chosen = model or models.roles["primary"]
    prompts = prompt_library(settings)
    limits = models.limits_for(condition.value)
    board = Blackboard.open_case(
        store,
        case_id=case_id,
        offer=offer,
        condition=condition,
        mode=settings.mode,
        gateway=gateway,
        config=case_config(settings, registry, models, chosen, limits, prompts.version),
    )
    ctx = ToolContext.create(case_id, settings, registry)
    belt = ToolBelt(ctx, board)
    runner = AgentRunner(
        llm,
        belt,
        board,
        model=chosen,
        decoding=models.decoding,
        limits=limits,
        meter=UsageMeter(max_requests=limits.requests_per_case),
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
        language=load_language_policy(settings.policies_dir),
        covered_regulators=covered_regulators(ctx.sources, settings),
    )


@dataclass
class CrewStack:
    """What every case in one process shares. Each case gets its own environment from it."""

    settings: Settings
    registry: DataRegistry
    gateway: MaskingGateway
    llm: GuardedLLM
    store: EventStore
    models: ModelsPolicy

    def open_case(
        self,
        case_id: str,
        offer: OfferInput,
        *,
        condition: SystemCondition = SystemCondition.CREW_FULL,
        model: str | None = None,
        models: ModelsPolicy | None = None,
    ) -> AgentEnv:
        return open_case_env(
            store=self.store,
            settings=self.settings,
            registry=self.registry,
            gateway=self.gateway,
            llm=self.llm,
            case_id=case_id,
            offer=offer,
            condition=condition,
            model=model,
            models=models or self.models,
        )


def build_stack(
    settings: Settings, transport: ChatTransport, store: EventStore, models: ModelsPolicy
) -> CrewStack:
    """Load the data this mode allows, and put the masking gateway in front of the model."""
    registry = DataRegistry(settings, load_sources_policy(settings.policies_dir))
    gateway = MaskingGateway(registry.restricted_values())
    return CrewStack(
        settings=settings,
        registry=registry,
        gateway=gateway,
        llm=GuardedLLM(transport, gateway),
        store=store,
        models=models,
    )


__all__ = [
    "Blackboard",
    "CrewStack",
    "build_crew",
    "build_stack",
    "covered_regulators",
    "open_case_env",
    "prompt_library",
]

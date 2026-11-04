"""One way to run any system under test, so that every condition is opened and logged alike.

:func:`open_condition` applies the only settings a condition may change. :func:`run_opened` runs it.
The commands and the API go through these two functions, and ``tests/test_fairness.py`` compares
what each condition records, so a difference nobody planned shows up as a failing test.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import date

from tessera.agents.base import Agent, AgentEnv
from tessera.agents.crew import CrewStack
from tessera.baseline.rules_only import run_rules_only
from tessera.baseline.single_agent import SingleConfig, run_single_agent
from tessera.errors import PolicyError
from tessera.governance.synthetic_gate import OfferInput
from tessera.llm.config import ModelsPolicy
from tessera.orchestration.conditions import CONDITIONS
from tessera.orchestration.graph import run_crew
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import AgentId, ResultCode
from tessera.protocol.results import FinalResult

SC5_RUNS = 5
#: Marks a sampled run of SA-SC5, so a list of cases can leave it out.
SAMPLE_MARK = ".run"
SC5_TEMPERATURE = 0.7
#: SA-MAX gets longer outputs, standing in for the crew's total output until Part 6 measures it.
SA_MAX_TOKEN_FACTOR = 2
SINGLE: dict[SystemCondition, SingleConfig] = {
    SystemCondition.SA_BASE: SingleConfig(),
    SystemCondition.SA_VER: SingleConfig(verifier=True, max_remediations=1),
    SystemCondition.SA_MAX: SingleConfig(),
    SystemCondition.SA_LARGER: SingleConfig(),
    SystemCondition.SA_SC5: SingleConfig(),
}
#: A tie goes to the more cautious result, as an unresolved point does under P7.
_CAUTION = (ResultCode.UNVERIFIED, ResultCode.CONFLICTS, ResultCode.CONSISTENT)


def models_for(models: ModelsPolicy, condition: SystemCondition) -> ModelsPolicy:
    """The settings a condition runs on. Each change here is what that condition tests."""
    if condition is SystemCondition.SA_SC5:
        return models.with_decoding(temperature=SC5_TEMPERATURE)
    if condition is SystemCondition.SA_MAX:
        tokens = models.decoding.max_tokens * SA_MAX_TOKEN_FACTOR
        return models.with_thinking(True).with_decoding(max_tokens=tokens)
    return models


def model_for(models: ModelsPolicy, condition: SystemCondition) -> str:
    role = "larger_single" if condition is SystemCondition.SA_LARGER else "primary"
    return models.roles[role]


def open_condition(
    stack: CrewStack,
    case_id: str,
    offer: OfferInput,
    *,
    condition: SystemCondition,
    model: str | None = None,
) -> AgentEnv:
    """Admit an offer under a condition. Refuses anything not marked synthetic."""
    if (
        condition not in CONDITIONS
        and condition not in SINGLE
        and (condition is not SystemCondition.RULES_ONLY)
    ):
        raise PolicyError(f"{condition} is not a system that can run")
    models = models_for(stack.models, condition)
    return stack.open_case(
        case_id,
        offer,
        condition=condition,
        model=model or model_for(stack.models, condition),
        models=models,
    )


@dataclass(frozen=True)
class _Vote:
    env: AgentEnv
    final: FinalResult


def _winner(votes: list[_Vote]) -> _Vote:
    counts = Counter(vote.final.result for vote in votes)
    most = max(counts.values())
    tied = [code for code in _CAUTION if counts[code] == most]
    return next(vote for vote in votes if vote.final.result is tied[0])


async def _self_consistency(
    stack: CrewStack, env: AgentEnv, offer: OfferInput, *, today: date
) -> FinalResult:
    """SA-SC5: a majority vote over several sampled runs, as a control for extra compute."""
    assert env.board.case is not None
    condition = env.board.case.condition
    model = env.board.case.config["model"]
    base = models_for(stack.models, condition)

    async def one(index: int) -> _Vote:
        sampled = base.with_decoding(seed=(base.decoding.seed or 0) + index)
        run = stack.open_case(
            f"{env.board.case_id}{SAMPLE_MARK}{index + 1}",
            offer,
            condition=condition,
            model=model,
            models=sampled,
        )
        return _Vote(run, await run_single_agent(run, SINGLE[condition], today=today))

    votes = list(await asyncio.gather(*(one(index) for index in range(SC5_RUNS))))
    chosen = _winner(votes)
    env.board.add_evidence(chosen.env.board.evidence.values())
    meters = [vote.env.runner.meter for vote in votes]
    detail = {
        **chosen.final.detail,
        "votes": dict(Counter(vote.final.result.value for vote in votes)),
        "requests": sum(meter.requests for meter in meters),
        "prompt_tokens": sum(meter.prompt_tokens for meter in meters),
        "completion_tokens": sum(meter.completion_tokens for meter in meters),
    }
    env.board.record("votes.counted", AgentId.ORC, {"votes": detail["votes"]})
    return env.board.finalize(chosen.final.model_copy(update={"detail": detail}))


async def run_opened(
    stack: CrewStack,
    env: AgentEnv,
    offer: OfferInput,
    *,
    today: date,
    crew: dict[AgentId, Agent] | None = None,
) -> FinalResult:
    """Run a case opened by :func:`open_condition` to its final result."""
    assert env.board.case is not None
    condition = env.board.case.condition
    if condition in CONDITIONS:
        return await run_crew(env, crew=crew, today=today)
    if condition is SystemCondition.RULES_ONLY:
        return run_rules_only(env, today=today)
    if condition is SystemCondition.SA_SC5:
        return await _self_consistency(stack, env, offer, today=today)
    return await run_single_agent(env, SINGLE[condition], today=today)

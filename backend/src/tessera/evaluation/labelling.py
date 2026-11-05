"""Labels come from the decision-policy engine, not from whoever wrote the item.

:func:`policy_label` gives the engine a perfect reading of an offer, runs the real tools on the real
snapshots, and returns what the policy derives. It calls no model. People then check these labels
without seeing them (§11.2 B), so the engine is not the last word, but it is the first.

It uses :class:`ToolCrew`, where scope comes from the scenario. RULES-ONLY's own guess at scope from
register wording plays no part, so that baseline does not get scope right by construction.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from tessera.agents.crew import CrewStack
from tessera.baseline.rules_only import Reading, ToolCrew
from tessera.governance.synthetic_gate import OfferInput
from tessera.orchestration.decision import PolicyDecision, derive_decision
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import ResultCode


def with_quotes_from(reading: Reading, masked_text: str) -> Reading:
    """Keep the reading usable on reworded text.

    A paraphrase may change the activity's words. What it says is unchanged, and a finding needs
    only some quote from the offer, so the opening words stand in for any that have gone. They come
    from the masked text, where a restricted name is one word and cannot be cut in half.
    """
    fallback = " ".join(masked_text.split()[:4])
    activities = tuple(
        (code, words if words.casefold() in masked_text.casefold() else fallback)
        for code, words in reading.activities
    )
    regulator = reading.regulator
    if regulator and regulator[1].casefold() not in masked_text.casefold():
        regulator = (regulator[0], fallback)
    return replace(reading, activities=activities, regulator=regulator)


def policy_label(
    stack: CrewStack, case_id: str, text: str, reading: Reading, *, today: date
) -> PolicyDecision:
    """What the policy derives from this text, when it is read perfectly."""
    offer = OfferInput(text=text, synthetic=True, corpus_item_id=case_id)
    env = stack.open_case(case_id, offer, condition=SystemCondition.RULES_ONLY)
    assert env.board.case is not None
    ToolCrew(env, with_quotes_from(reading, env.board.case.offer_text)).run()
    return derive_decision(env, today=today)


def reasons_of(decision: PolicyDecision) -> tuple[str, ...]:
    """The hard conflicts behind a conflict, and otherwise the reasons it could not be verified."""
    if decision.result is ResultCode.CONFLICTS:
        return decision.hard_conflict_ids
    return decision.unverified_reasons

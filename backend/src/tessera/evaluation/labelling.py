"""Labels come from the decision-policy engine, not from whoever wrote the item.

:func:`policy_label` gives the engine a perfect reading of an offer, runs the real tools on the real
snapshots, and returns what the policy derives. It calls no model. People then check these labels
without seeing them (§11.2 B), so the engine is not the last word, but it is the first.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from tessera.agents.crew import CrewStack
from tessera.baseline.rules_only import Reading, RulesOnly
from tessera.governance.synthetic_gate import OfferInput
from tessera.orchestration.decision import PolicyDecision, derive_decision
from tessera.protocol.case import SystemCondition


@dataclass(frozen=True)
class Label:
    decision: PolicyDecision
    relevant: tuple[str, ...]


def with_quotes_from(reading: Reading, text: str) -> Reading:
    """Keep the reading usable on reworded text.

    A paraphrase may change the activity's words. What it says is unchanged, and a finding needs
    only some quote from the offer, so the opening words stand in for any that have gone.
    """
    fallback = " ".join(text.split()[:4])
    activities = tuple(
        (code, words if words.casefold() in text.casefold() else fallback)
        for code, words in reading.activities
    )
    regulator = reading.regulator
    if regulator and regulator[1].casefold() not in text.casefold():
        regulator = (regulator[0], fallback)
    return replace(reading, activities=activities, regulator=regulator)


def policy_label(
    stack: CrewStack, case_id: str, text: str, reading: Reading, *, today: date
) -> Label:
    """What the policy derives from this text, when it is read perfectly."""
    offer = OfferInput(text=text, synthetic=True, corpus_item_id=case_id)
    env = stack.open_case(case_id, offer, condition=SystemCondition.RULES_ONLY)
    crew = RulesOnly(env, with_quotes_from(reading, text))
    crew.run()
    decision = derive_decision(env, today=today)
    return Label(decision, tuple(sorted(env.board.relevant_regulators())))

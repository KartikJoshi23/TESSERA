"""Building the message-level set: scenario, text, automatic checks, label (§11.2 B)."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from tessera.agents.crew import CrewStack
from tessera.evaluation.firms import World
from tessera.evaluation.items import EvalItem, Level
from tessera.evaluation.labelling import policy_label
from tessera.evaluation.scenarios import GENERATOR, Scenario
from tessera.evaluation.validators import check_message
from tessera.evaluation.writing import origin_mix, paraphrase_messages, render_template
from tessera.protocol.common import ResultCode

PARAPHRASE_MAX_TOKENS = 500


@dataclass(frozen=True)
class MessageSet:
    items: tuple[EvalItem, ...]
    #: Scenarios left for a person to write.
    for_people: tuple[Scenario, ...]
    #: Every item dropped, with its reasons. Nothing is dropped silently.
    dropped: tuple[str, ...]


def _reasons(
    stack_result: ResultCode, conflicts: tuple[str, ...], reasons: tuple[str, ...]
) -> tuple[str, ...]:
    return conflicts if stack_result is ResultCode.CONFLICTS else reasons


def to_item(
    scenario: Scenario,
    text: str,
    origin: str,
    stack: CrewStack,
    world: World,
    *,
    today: date,
) -> tuple[EvalItem | None, list[str]]:
    """Check one message, and give it the policy's label."""
    item_id = f"M-{scenario.scenario_id}"
    label = policy_label(stack, f"label-{item_id}", text, scenario.reading, today=today)
    derived = label.decision.result
    problems = check_message(text, scenario, world, derived)
    if problems:
        return None, problems
    item = EvalItem(
        item_id=item_id,
        level=Level.MESSAGE,
        text=text,
        gold_label=derived,
        gold_reasons=_reasons(
            derived, label.decision.hard_conflict_ids, label.decision.unverified_reasons
        ),
        gold_relevant=tuple(sorted(scenario.reading.relevant)),
        factors=scenario.factors,
        origin=origin,  # type: ignore[arg-type]
        scenario_id=scenario.scenario_id,
        generator=GENERATOR,
        restricted=scenario.restricted,
    )
    return item, []


async def paraphrase(stack: CrewStack, scenario: Scenario, text: str) -> str:
    """Reword a message with a model from another family. Restricted values go as placeholders."""
    payload = {
        "model": stack.models.roles["paraphrase"],
        "messages": paraphrase_messages(text, scenario.keep),
        "temperature": 0.7,
        "max_tokens": PARAPHRASE_MAX_TOKENS,
    }
    response = await stack.llm.complete(payload)
    return stack.gateway.unmask(response.content or "").strip()


async def build_message_items(
    scenarios: Sequence[Scenario],
    stack: CrewStack,
    world: World,
    *,
    today: date,
    seed: int,
    use_model: bool,
    people: bool,
) -> MessageSet:
    """Write and check every scenario.

    ``use_model`` off makes paraphrases into templates, for a dry run with no requests. ``people``
    off does the same for the share people would write.
    """
    rng = random.Random(seed)
    origins = origin_mix(len(scenarios), seed=seed)
    items: list[EvalItem] = []
    later: list[Scenario] = []
    dropped: list[str] = []
    for scenario, origin in zip(scenarios, origins, strict=True):
        if origin == "human" and people:
            later.append(scenario)
            continue
        text = render_template(scenario, rng)
        final_origin = "template"
        if origin == "paraphrase" and use_model:
            text = await paraphrase(stack, scenario, text)
            final_origin = "paraphrase"
        item, problems = to_item(scenario, text, final_origin, stack, world, today=today)
        if item is None:
            dropped.append(f"{scenario.scenario_id} ({scenario.recipe}): {'; '.join(problems)}")
        else:
            items.append(item)
    return MessageSet(tuple(items), tuple(later), tuple(dropped))


def import_written(
    written: Mapping[str, str],
    scenarios: Sequence[Scenario],
    stack: CrewStack,
    world: World,
    *,
    today: date,
) -> MessageSet:
    """Bring in messages people wrote. They pass the same checks as everything else."""
    items: list[EvalItem] = []
    dropped: list[str] = []
    for scenario in scenarios:
        text = written.get(scenario.scenario_id, "").strip()
        if not text:
            continue
        item, problems = to_item(scenario, text, "human", stack, world, today=today)
        if item is None:
            dropped.append(f"{scenario.scenario_id}: {'; '.join(problems)}")
        else:
            items.append(item)
    return MessageSet(tuple(items), (), tuple(dropped))

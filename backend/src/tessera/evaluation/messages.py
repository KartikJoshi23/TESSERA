"""Building the message-level set: scenario, text, automatic checks, label (§11.2 B)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from tessera.agents.crew import CrewStack
from tessera.evaluation.firms import World
from tessera.evaluation.items import EvalItem, Level
from tessera.evaluation.labelling import policy_label, reasons_of
from tessera.evaluation.scenarios import GENERATOR, Scenario
from tessera.evaluation.validators import check_message
from tessera.evaluation.writing import origin_mix, paraphrase_messages, render_template
from tessera.llm.types import LLMError

#: The paraphrase model reasons before it writes, and that counts against this. At 500, most replies
#: ran out of room and came back empty.
PARAPHRASE_MAX_TOKENS = 2000
#: A model may refuse or lose a kept string on one try and not on the next, so an unusable reply
#: gets one more. Nothing about the scenario changes between tries.
PARAPHRASE_TRIES = 2
MAX_PARAPHRASE_FAILURES = 3
#: Paraphrases in flight at once. A reply waits a minute or two in the provider's queue, so one at a
#: time used a fraction of the rate limit, which the shared limiter still enforces.
PARAPHRASE_CONCURRENCY = 4


@dataclass(frozen=True)
class MessageSet:
    items: tuple[EvalItem, ...]
    #: Scenarios left for a person to write.
    for_people: tuple[Scenario, ...]
    #: Every item dropped, with its reasons. Nothing is dropped silently.
    dropped: tuple[str, ...]


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
    decision = policy_label(stack, f"label-{item_id}", text, scenario.reading, today=today)
    derived = decision.result
    problems = check_message(text, scenario, world, derived)
    if problems:
        return None, problems
    item = EvalItem(
        item_id=item_id,
        level=Level.MESSAGE,
        text=text,
        gold_label=derived,
        gold_reasons=reasons_of(decision),
        gold_relevant=tuple(sorted(scenario.reading.relevant)),
        contacts=tuple(
            scenario.slots[slot] for slot in ("domain", "whatsapp") if slot in scenario.slots
        ),
        factors=scenario.factors,
        origin=origin,  # type: ignore[arg-type]
        scenario_id=scenario.scenario_id,
        generator=GENERATOR,
        restricted=scenario.restricted,
    )
    return item, []


async def paraphrase(stack: CrewStack, scenario: Scenario, text: str) -> str:
    """Reword a message with a model from another family. Restricted values go as placeholders.

    The model's own options in policies/models.yaml apply, as they do to every other request.
    """
    model = stack.models.roles["paraphrase"]
    payload = {
        "model": model,
        "messages": paraphrase_messages(text, scenario.keep),
        "temperature": 0.7,
        "max_tokens": PARAPHRASE_MAX_TOKENS,
        **stack.models.options_for(model),
    }
    response = await stack.llm.complete(payload)
    return stack.gateway.unmask(response.content or "").strip()


def _accept(
    scenario: Scenario,
    text: str,
    origin: str,
    stack: CrewStack,
    world: World,
    seen: set[str],
    *,
    today: date,
) -> tuple[EvalItem | None, list[str]]:
    """One text, checked. Its wording is remembered only if it becomes an item."""
    same = " ".join(text.casefold().split())
    if not same or same in seen:
        return None, ["empty or repeated text"]
    item, problems = to_item(scenario, text, origin, stack, world, today=today)
    if item is not None:
        seen.add(same)
    return item, problems


async def _reworded(
    scenario: Scenario,
    template: str,
    stack: CrewStack,
    world: World,
    seen: set[str],
    *,
    today: date,
) -> tuple[EvalItem | None, list[str]]:
    """A paraphrase that passes every check, or the problems with the last try."""
    problems: list[str] = []
    for _ in range(PARAPHRASE_TRIES):
        text = await paraphrase(stack, scenario, template)
        item, problems = _accept(scenario, text, "paraphrase", stack, world, seen, today=today)
        if item is not None:
            return item, []
    return None, problems


async def build_message_items(
    scenarios: Sequence[Scenario],
    stack: CrewStack,
    world: World,
    *,
    today: date,
    seed: int,
    use_model: bool,
    people: bool,
    echo: Callable[[str], None] = lambda _line: None,
) -> MessageSet:
    """Write and check every scenario.

    ``use_model`` off makes paraphrases into templates, for a dry run with no requests. ``people``
    off does the same for the share people would write. ``echo`` hears of each scenario as it is
    done, so a long run shows where it is.

    Templates are rendered first, in order, so a seed always gives the same texts. Paraphrases then
    run a few at a time, and results are gathered in scenario order, so the files come out the same
    way whatever order the replies arrive in.
    """
    rng = random.Random(seed)
    origins = origin_mix(len(scenarios), seed=seed)
    later: list[Scenario] = []
    planned: list[tuple[Scenario, str, bool]] = []
    for scenario, origin in zip(scenarios, origins, strict=True):
        if origin == "human" and people:
            later.append(scenario)
            continue
        by_model = origin == "paraphrase" and use_model
        planned.append((scenario, render_template(scenario, rng), by_model))

    seen: set[str] = set()
    results: dict[int, tuple[EvalItem | None, list[str]]] = {}

    def settled(index: int, scenario: Scenario, item: EvalItem | None) -> None:
        echo(f"{scenario.scenario_id}: {'kept as ' + item.origin if item else 'dropped'}")

    for index, (scenario, text, by_model) in enumerate(planned):
        if not by_model:
            results[index] = _accept(scenario, text, "template", stack, world, seen, today=today)
            settled(index, scenario, results[index][0])

    failures = 0
    stopped = False
    gate = asyncio.Semaphore(PARAPHRASE_CONCURRENCY)

    async def paraphrased(index: int, scenario: Scenario, template: str) -> None:
        nonlocal failures, stopped
        async with gate:
            if stopped:
                results[index] = (None, ["not paraphrased: the model kept failing"])
                return
            echo(f"{scenario.scenario_id}: paraphrasing")
            try:
                results[index] = await _reworded(
                    scenario, template, stack, world, seen, today=today
                )
            except LLMError as exc:
                # What is built so far has cost requests, so a failure must not lose it.
                results[index] = (None, [f"paraphrase failed ({type(exc).__name__})"])
                echo(f"{scenario.scenario_id}: paraphrase failed")
                failures += 1
                stopped = stopped or failures >= MAX_PARAPHRASE_FAILURES
                return
            failures = 0
            settled(index, scenario, results[index][0])

    await asyncio.gather(
        *(paraphrased(i, s, text) for i, (s, text, by_model) in enumerate(planned) if by_model)
    )
    items: list[EvalItem] = []
    dropped: list[str] = []
    for index, (scenario, _, _) in enumerate(planned):
        item, problems = results[index]
        if item is None:
            dropped.append(f"{scenario.scenario_id} ({scenario.recipe}): {'; '.join(problems)}")
        else:
            items.append(item)
    if stopped:
        dropped.append("stopped: the paraphrase model keeps failing")
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

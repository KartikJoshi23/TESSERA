"""Turning a scenario into message text (§11.2 B).

Three sources: fixed templates, free paraphrase by a model from a different family than the system
under test, and messages written by people. A paraphrase sees a restricted value only as its
placeholder, like every other model call.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Protocol

from tessera.evaluation.scenarios import Scenario

#: Openers and closers that say nothing about the record.
_END = "{contact_part}{reference_part}"
_PLAIN = (
    "Hello, {firm} here. We can help with {activity}{claim_part}. " + _END,
    "Thinking about {activity}? {firm}{claim_part} would love to hear from you. " + _END,
    "Good morning! A quick note from the team at {firm}{claim_part}: "
    "{activity} is now open to new clients. " + _END,
    "Our clients in Dubai keep asking about {activity}, so {firm}{claim_part} "
    "has room for a few more. " + _END,
    "{firm}{claim_part}: {activity}, explained simply. " + _END,
)
_PRESSURE = (
    "ONLY 3 PLACES LEFT!!! {firm}{claim_part} is closing {activity} to new clients TONIGHT. "
    "Do not miss this. " + _END,
    "Last chance!! Everyone in your building has already joined {firm}{claim_part} "
    "for {activity}. Act now. " + _END,
)
_NOTICE = (
    "URGENT {claim}: {activity} has been flagged. "
    "Complete your verification within 24 hours at {domain}.",
    "Official {claim}. Your access to {activity} will be suspended "
    "unless you confirm your details at {domain} today.",
)
_CONTACT = (
    "Details at {domain}.",
    "Everything is on {domain}.",
    "You will find us at {domain}.",
    "Sign up through {domain}.",
)
_WHATSAPP = (
    "Message me on WhatsApp {whatsapp}.",
    "WhatsApp only please: {whatsapp}.",
)
_PAYMENT = " To fund your account, transfer to beneficiary {beneficiary}, IBAN {iban}."
_REFERENCE = (" Reference {reference}.", " Our number is {reference}.")


def render_template(scenario: Scenario, rng: random.Random) -> str:
    """Fill a template. Everything a result turns on goes in word for word."""
    slots = scenario.slots
    if scenario.tone == "notice":
        return rng.choice(_NOTICE).format(**slots)
    contact = ""
    if "domain" in slots:
        contact = rng.choice(_CONTACT).format(domain=slots["domain"])
    elif "whatsapp" in slots:
        contact = rng.choice(_WHATSAPP).format(whatsapp=slots["whatsapp"])
    if "beneficiary" in slots:
        contact += _PAYMENT.format(beneficiary=slots["beneficiary"], iban=slots["iban"])
    reference = rng.choice(_REFERENCE).format(**slots) if "reference" in slots else ""
    claim = f", {slots['claim']}," if "claim" in slots else ""
    shapes = _PRESSURE if scenario.tone == "pressure" else _PLAIN
    text = rng.choice(shapes).format(
        firm=slots["firm"],
        activity=slots["activity"],
        claim_part=claim,
        contact_part=contact,
        reference_part=reference,
    )
    text = text.replace(",,", ",").replace(",.", ".").replace(", :", ":")
    if "address" in slots:
        text = f"{text} Office: {slots['address']}."
    if "aside" in slots:
        text = f"{text} {slots['aside']}"
    return text


class Completion(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


PARAPHRASE_SYSTEM = (
    "You rewrite clearly synthetic offer messages for a research dataset. The firms and details "
    "are invented or masked. Keep the meaning, and keep each listed string exactly as written, "
    "including any placeholder in double square brackets. Do not add contact details, firms, "
    "numbers or claims. Reply with the rewritten message and nothing else."
)


def paraphrase_messages(text: str, keep: tuple[str, ...]) -> list[dict[str, str]]:
    listed = "\n".join(f"- {item}" for item in keep)
    return [
        {"role": "system", "content": PARAPHRASE_SYSTEM},
        {
            "role": "user",
            "content": (
                "Rewrite this message in a different voice, as a real marketer might send it. "
                f"Keep these strings exactly:\n{listed}\n\nMessage:\n{text}"
            ),
        },
    ]


@dataclass(frozen=True)
class Written:
    text: str
    origin: str


def origin_mix(total: int, *, seed: int) -> list[str]:
    """About 30% templates, 50% paraphrases and 20% written by people, in a shuffled order."""
    human = round(total * 0.2)
    paraphrase = round(total * 0.5)
    origins = ["human"] * human + ["paraphrase"] * paraphrase
    origins += ["template"] * (total - len(origins))
    random.Random(seed).shuffle(origins)
    return origins


def writing_brief(scenario: Scenario) -> dict[str, Any]:
    """What a person needs in order to write the message. It holds no label."""
    return {
        "scenario_id": scenario.scenario_id,
        "must_appear_exactly": list(scenario.keep),
        "tone": scenario.tone,
        "text": "",
    }

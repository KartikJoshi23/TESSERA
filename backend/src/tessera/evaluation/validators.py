"""Automatic checks on generated messages (§11.2 B, step 3).

Each check returns a list of problems, so a report can show every reason an item was dropped.
Dropped items are logged, never silently fixed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from tessera.evaluation.firms import World
from tessera.evaluation.scenarios import Scenario
from tessera.governance.synthetic_gate import pii_warnings
from tessera.normalize.domains import registrable_domain
from tessera.protocol.common import ResultCode

_DOMAIN = re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,24}\b", re.IGNORECASE)
#: Reserved for documentation and testing (RFC 2606 and RFC 6761).
_RESERVED_ENDINGS = (".example", ".test", ".invalid")


def missing_facts(text: str, keep: Iterable[str]) -> list[str]:
    """Everything a result turns on must appear word for word."""
    folded = " ".join(text.split()).casefold()
    return [
        f"missing {value!r}" for value in keep if " ".join(value.split()).casefold() not in folded
    ]


def _official_domains(world: World) -> set[str]:
    domains = {firm.domain for firm in world.firms if firm.domain}
    for entry in world.listed:
        domains |= {registrable_domain(contact) or contact for contact in entry.contacts}
    return {domain for domain in domains if domain}


def stray_identifiers(text: str, scenario: Scenario, world: World) -> list[str]:
    """A domain nobody chose: a model can invent one that belongs to a real company."""
    expected = {value.casefold() for value in scenario.keep}
    known = _official_domains(world)
    problems = []
    for found in _DOMAIN.findall(text):
        domain = found.casefold()
        if (
            domain not in expected
            and domain not in known
            and not domain.endswith(_RESERVED_ENDINGS)
        ):
            problems.append(f"unexpected domain {found!r}")
    return problems


def personal_data(text: str, *, allowed_phones: Iterable[str] = ()) -> list[str]:
    """Anything that looks like a real person's details, apart from the record's own numbers."""
    allowed = {re.sub(r"\D", "", phone)[-4:] for phone in allowed_phones}
    return [
        warning.message
        for warning in pii_warnings(text)
        if not (warning.kind == "phone" and warning.excerpt.lstrip("…") in allowed)
    ]


def label_problem(intended: ResultCode, derived: ResultCode) -> list[str]:
    if intended is derived:
        return []
    return [f"the recipe intended {intended.value} but the policy derives {derived.value}"]


def check_message(text: str, scenario: Scenario, world: World, derived: ResultCode) -> list[str]:
    """Every automatic check on one message."""
    return [
        *missing_facts(text, scenario.keep),
        *stray_identifiers(text, scenario, world),
        *personal_data(text, allowed_phones=[f.phone for f in world.firms if f.phone]),
        *label_problem(scenario.intended, derived),
    ]

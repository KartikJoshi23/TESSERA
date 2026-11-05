"""Automatic checks on generated messages (§11.2 B, step 3).

Each check returns a list of problems, so a report can show every reason an item was dropped.
Dropped items are logged, never silently fixed.
"""

from __future__ import annotations

from collections.abc import Iterable

from tessera.evaluation.firms import World
from tessera.evaluation.leakage import names_in
from tessera.evaluation.scenarios import Scenario
from tessera.governance.synthetic_gate import pii_warnings
from tessera.normalize.domains import registrable_domain
from tessera.protocol.common import ResultCode
from tessera.protocol.contacts import ContactKind
from tessera.tools.extract import extract_contact_points

#: Reserved for documentation and testing (RFC 2606 and RFC 6761).
_RESERVED_ENDINGS = (".example", ".test", ".invalid")
_DOMAIN_KINDS = (ContactKind.URL, ContactKind.DOMAIN, ContactKind.EMAIL)


def missing_facts(text: str, keep: Iterable[str]) -> list[str]:
    """Everything a result turns on must appear word for word."""
    folded = " ".join(text.split()).casefold()
    return [
        f"missing {value!r}" for value in keep if " ".join(value.split()).casefold() not in folded
    ]


def _on_record(world: World) -> set[str]:
    domains = {firm.domain for firm in world.firms if firm.domain}
    for entry in world.listed:
        domains |= {registrable_domain(contact) or contact for contact in entry.contacts}
    return {domain.casefold() for domain in domains if domain}


def stray_identifiers(text: str, scenario: Scenario, world: World) -> list[str]:
    """A real identifier nobody chose: a model can add a site or a firm that was not in the plan.

    Being on a register is no excuse. The label was worked out for the scenario, so a firm or domain
    it does not include would make the message say something the label does not cover.
    """
    expected = {(registrable_domain(value) or value).casefold() for value in scenario.keep}
    on_record = _on_record(world)
    problems = []
    for point in extract_contact_points(text):
        if point.kind not in _DOMAIN_KINDS:
            continue
        domain = (registrable_domain(point.normalized) or point.normalized).casefold()
        if domain not in expected and (
            domain in on_record or not domain.endswith(_RESERVED_ENDINGS)
        ):
            problems.append(f"unexpected domain {domain!r}")
    folded = text.casefold()
    kept = " ".join(scenario.keep).casefold()
    problems += [
        f"unexpected firm {name!r}"
        for name in sorted(names_in(world))
        if name.casefold() in folded and name.casefold() not in kept
    ]
    return problems


def personal_data(text: str) -> list[str]:
    """Anything that looks like a real person's details. No recipe uses a real person's number."""
    return [warning.message for warning in pii_warnings(text)]


def label_problem(intended: ResultCode, derived: ResultCode) -> list[str]:
    if intended is derived:
        return []
    return [f"the recipe intended {intended.value} but the policy derives {derived.value}"]


def check_message(text: str, scenario: Scenario, world: World, derived: ResultCode) -> list[str]:
    """Every automatic check on one message."""
    return [
        *missing_facts(text, scenario.keep),
        *stray_identifiers(text, scenario, world),
        *personal_data(text),
        *label_problem(scenario.intended, derived),
    ]

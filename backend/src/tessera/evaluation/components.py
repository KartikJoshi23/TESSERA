"""Component checks (§11.2 C): when a system is wrong, was it a tool or the reasoning?

These call no model. A wrong answer with a working matcher points at the reasoning, and a tool that
misses here would explain a wrong answer without any model being at fault.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from tessera.evaluation.firms import World
from tessera.evaluation.items import EvalItem
from tessera.evaluation.scenarios import lookalike, respelled
from tessera.governance.policies import Thresholds
from tessera.normalize.domains import registrable_domain
from tessera.tools.domain_analysis import compare_domains
from tessera.tools.extract import extract_contact_points
from tessera.tools.matching import match_name

#: Any of these counts as the matcher finding the entry.
_FOUND = frozenset({"exact", "alias", "fuzzy"})
_UNRELATED_DOMAINS = ("marketnotes42.example", "clientdesk7.example", "dailybrief.example")
_UNRELATED_NAMES = ("Northern Sand Holdings", "Quiet Harbor Trading", "Blue Lantern Logistics")


@dataclass(frozen=True)
class Score:
    """Hits among the things that should be found, and false alarms among those that should not."""

    positives: int
    found: int
    negatives: int
    false_alarms: int

    @property
    def recall(self) -> float | None:
        return self.found / self.positives if self.positives else None

    @property
    def precision(self) -> float | None:
        flagged = self.found + self.false_alarms
        return self.found / flagged if flagged else None


def name_matcher(world: World, thresholds: Thresholds) -> Score:
    """Short names and respellings should find their entry. Unrelated names should find nothing."""
    entries = [(firm.record_id, [firm.name, *firm.aliases]) for firm in world.firms]

    def matches(query: str, wanted: str | None) -> bool:
        found = match_name(
            query,
            entries,
            tau1=thresholds.name_fuzzy_tau1,
            tau2=thresholds.name_partial_tau2,
            partial_min_length=thresholds.partial_min_length,
        )
        hits = [match for match in found if match.match_type in _FOUND]
        return any(match.record_id == wanted for match in hits) if wanted else bool(hits)

    variants: list[tuple[str, str]] = []
    for firm in world.firms:
        variants.append((firm.short_name, firm.record_id))
        if spelled := respelled(firm.name):
            variants.append((spelled, firm.record_id))
    found = sum(matches(query, wanted) for query, wanted in variants)
    alarms = sum(matches(name, None) for name in _UNRELATED_NAMES)
    return Score(len(variants), found, len(_UNRELATED_NAMES), alarms)


def lookalike_detector(world: World, thresholds: Thresholds, *, seed: int) -> Score:
    """Imitations of an official domain should be flagged, and unrelated domains should not."""
    rng = random.Random(seed)
    officials = [firm.domain for firm in world.firms if firm.domain]

    def flagged(offer: str, official: str) -> bool:
        return compare_domains(
            offer,
            official,
            max_edit_distance=thresholds.lookalike_max_edit_distance,
            min_similarity=thresholds.lookalike_min_similarity,
            min_brand_length=thresholds.lookalike_min_brand_length,
        ).lookalike

    fakes = [(lookalike(domain, rng), domain) for domain in officials for _ in range(3)]
    found = sum(flagged(offer, official) for offer, official in fakes if offer != official)
    pairs = [(other, domain) for domain in officials for other in _UNRELATED_DOMAINS]
    return Score(len(fakes), found, len(pairs), sum(flagged(a, b) for a, b in pairs))


def contact_extraction(items: Iterable[EvalItem]) -> Score:
    """Every contact an item was built with should be extracted from its text."""
    positives = found = 0
    for item in items:
        if not item.contacts:
            continue
        points = extract_contact_points(item.text)
        seen = {_plain(point.raw) for point in points} | {
            _plain(point.normalized) for point in points
        }
        for contact in item.contacts:
            positives += 1
            found += _plain(contact) in seen
    return Score(positives, found, 0, 0)


def _plain(value: str) -> str:
    """A contact in the form extraction compares on."""
    digits = "".join(ch for ch in value if ch.isdigit())
    if value.lstrip().startswith("+") or (digits and len(digits) >= len(value) - 4):
        return digits[-9:]
    return (registrable_domain(value) or value).casefold()


def component_report(
    world: World, thresholds: Thresholds, items: Sequence[EvalItem], *, seed: int
) -> dict[str, Score]:
    return {
        "name matcher": name_matcher(world, thresholds),
        "look-alike detector": lookalike_detector(world, thresholds, seed=seed),
        "contact extraction": contact_extraction(items),
    }

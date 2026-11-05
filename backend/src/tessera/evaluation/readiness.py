"""How close the real evaluation is to being able to start.

The evaluation depends on records people collect by hand, so what is missing is not obvious from the
code. This reads what is loaded and compares it with what the plan needs (§11.2 A), and it says what
is still to do in plain terms. It changes nothing and calls no model.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from tessera.data.registry import DataRegistry
from tessera.evaluation.entities import STRATA, near_misses
from tessera.evaluation.firms import World
from tessera.knowledge import ActivityTaxonomy

#: The least each stratum needs (§11.2 A). "All" strata take what the source holds.
STRATUM_TARGETS = {
    "E1": 15,
    "E2": 10,
    "E3": 10,
    "E4": 38,
    "E5": 30,
    "E6": 15,
    "E7": 40,
    "E8": 15,
    "E9": 1,
    "E11": 25,
}
REVISIONS = re.compile(r"\*\*Crew: (\d+) revisions?\. Single agent: (\d+)\.\*\*")


@dataclass(frozen=True)
class Check:
    name: str
    done: bool
    detail: str


def source_checks(registry: DataRegistry) -> list[Check]:
    checks = []
    for source_id, policy in registry.sources.sources.items():
        if not policy.enabled or policy.phase != 1:
            continue
        table = registry.table(source_id)
        rows = len(table.records)
        when = table.manifest.retrieved_on.isoformat() if table.manifest else "not loaded"
        checks.append(Check(policy.name, rows > 0, f"{rows} records ({when})"))
    return checks


def stratum_counts(world: World, taxonomy: ActivityTaxonomy, *, seed: int) -> Counter[str]:
    """How many cards each stratum could have now, before the policy has checked them."""
    cards = [card for build in STRATA for card in build(world, taxonomy)]
    cards += near_misses(world, taxonomy, seed=seed)
    return Counter(card.stratum for card in cards)


def stratum_checks(world: World, taxonomy: ActivityTaxonomy, *, seed: int) -> list[Check]:
    counts = stratum_counts(world, taxonomy, seed=seed)
    return [
        Check(f"Stratum {stratum}", counts[stratum] >= target, f"{counts[stratum]} of {target}")
        for stratum, target in STRATUM_TARGETS.items()
    ]


def prompt_check(changelog: Path) -> Check:
    """Both systems must get the same number of prompt revisions before anything is frozen."""
    found = REVISIONS.search(changelog.read_text(encoding="utf-8"))
    if found is None:
        return Check("Equal prompt revisions", False, "no count in the changelog")
    crew, single = int(found[1]), int(found[2])
    return Check("Equal prompt revisions", crew == single, f"crew {crew}, single agent {single}")


def readiness(
    registry: DataRegistry, world: World, taxonomy: ActivityTaxonomy, root: Path, *, seed: int
) -> list[Check]:
    return [
        *source_checks(registry),
        *stratum_checks(world, taxonomy, seed=seed),
        prompt_check(root / "backend" / "prompts" / "CHANGELOG.md"),
    ]

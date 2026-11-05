"""The registered statistics (§11.4), in plain Python so each one can be read and checked.

Every test here is paired: each system answers each item, so comparisons use the same items on both
sides. Randomness comes from an explicit seed, so a report can be reproduced exactly.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import comb
from typing import TypeVar

T = TypeVar("T")

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261105


def exact_mcnemar(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs.

    ``only_a`` is the number of items where A has the event and B does not, and ``only_b`` the
    reverse. Items where both agree say nothing about the difference, so they are not an input.
    """
    discordant = only_a + only_b
    if discordant == 0:
        return 1.0
    tail = sum(comb(discordant, k) for k in range(min(only_a, only_b) + 1)) / 2**discordant
    return min(1.0, 2 * tail)


def holm_bonferroni(p_values: Mapping[str, float]) -> dict[str, float]:
    """Holm's step-down adjustment, over a family of comparisons."""
    ordered = sorted(p_values.items(), key=lambda pair: pair[1])
    tests = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (tests - rank) * value))
        adjusted[name] = running
    return adjusted


@dataclass(frozen=True)
class Interval:
    estimate: float
    low: float
    high: float

    def excludes_zero(self) -> bool:
        return self.low > 0 or self.high < 0


def percentile(ordered: Sequence[float], share: float) -> float:
    """Linear interpolation between ranks, on sorted values."""
    position = share * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def paired_bootstrap(
    pairs: Sequence[T],
    statistic: Callable[[Sequence[T]], float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = 0.95,
) -> Interval:
    """A percentile interval for ``statistic``, resampling whole items so pairs stay together."""
    if not pairs:
        raise ValueError("no items to resample")
    rng = random.Random(seed)
    size = len(pairs)
    drawn = sorted(statistic(rng.choices(pairs, k=size)) for _ in range(resamples))
    tail = (1 - confidence) / 2
    return Interval(statistic(pairs), percentile(drawn, tail), percentile(drawn, 1 - tail))


def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> float:
    """Chance-corrected agreement between two sets of labels on the same items."""
    if len(first) != len(second):
        raise ValueError("both raters must label the same items")
    if not first:
        raise ValueError("no items to compare")
    total = len(first)
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / total
    counts_a, counts_b = Counter(first), Counter(second)
    expected = sum(counts_a[label] * counts_b[label] for label in counts_a) / total**2
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def fleiss_kappa(ratings: Sequence[Sequence[str]]) -> float:
    """Agreement across several runs of one system: one row per item, one column per run."""
    if not ratings:
        raise ValueError("no items to compare")
    raters = len(ratings[0])
    if raters < 2 or any(len(row) != raters for row in ratings):
        raise ValueError("every item needs the same number of runs, at least two")
    items = len(ratings)
    per_item = [Counter(row) for row in ratings]
    observed = (
        sum(
            (sum(count * count for count in counts.values()) - raters) / (raters * (raters - 1))
            for counts in per_item
        )
        / items
    )
    totals: Counter[str] = Counter()
    for counts in per_item:
        totals.update(counts)
    expected = sum((count / (items * raters)) ** 2 for count in totals.values())
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def mcnemar_power(
    items: int,
    rate_a: float,
    rate_b: float,
    *,
    shared: float = 0.5,
    alpha: float = 0.05,
    simulations: int = 2_000,
    seed: int = BOOTSTRAP_SEED,
) -> float:
    """How often the exact test finds a true difference between two paired rates.

    ``shared`` is the share of the smaller rate's failures that both systems make on the same item.
    Pairs fail together more often than chance would suggest, and that is what the test depends on.
    """
    both = min(rate_a, rate_b) * shared
    only_a = rate_a - both
    only_b = rate_b - both
    rng = random.Random(seed)
    found = 0
    for _ in range(simulations):
        a = b = 0
        for _item in range(items):
            draw = rng.random()
            if draw < only_a:
                a += 1
            elif draw < only_a + only_b:
                b += 1
        found += exact_mcnemar(a, b) < alpha
    return found / simulations

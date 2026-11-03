"""Name matching against register and list records.

A match is one of these types, best first:

* ``exact``: the normalised key equals the record's primary name;
* ``alias``: the key equals another listed name;
* ``fuzzy``: token-set similarity of at least τ₁;
* ``partial``: partial similarity of at least τ₂, for keys long enough to make that meaningful.

Thresholds live in ``policies/decision_policy.yaml`` and are tuned on the development split only.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from tessera.normalize.names import normalize_name

MATCH_RANK = {"reference": 0, "exact": 1, "alias": 2, "fuzzy": 3, "partial": 4}


@dataclass(frozen=True)
class NameMatch:
    record_id: str
    match_type: str
    score: float
    matched_name: str


def match_name(
    query: str,
    candidates: Iterable[tuple[str, Sequence[str]]],
    *,
    tau1: float,
    tau2: float,
    partial_min_length: int,
    limit: int = 5,
) -> list[NameMatch]:
    """Rank candidate records by how well one of their names matches ``query``."""
    key = normalize_name(query).key
    if not key:
        return []
    best: dict[str, NameMatch] = {}
    for record_id, names in candidates:
        for position, name in enumerate(names):
            other = normalize_name(name).key
            if not other:
                continue
            if other == key:
                found = NameMatch(record_id, "exact" if position == 0 else "alias", 100.0, name)
            else:
                score = fuzz.token_set_ratio(key, other)
                if score >= tau1:
                    found = NameMatch(record_id, "fuzzy", float(score), name)
                elif (
                    min(len(key), len(other)) >= partial_min_length
                    and (partial := fuzz.partial_ratio(key, other)) >= tau2
                ):
                    found = NameMatch(record_id, "partial", float(partial), name)
                else:
                    continue
            current = best.get(record_id)
            if current is None or (MATCH_RANK[found.match_type], -found.score) < (
                MATCH_RANK[current.match_type],
                -current.score,
            ):
                best[record_id] = found
    ranked = sorted(best.values(), key=lambda m: (MATCH_RANK[m.match_type], -m.score, m.record_id))
    return ranked[:limit]

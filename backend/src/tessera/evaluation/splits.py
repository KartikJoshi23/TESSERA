"""Development and test splits (§11.2).

The split is stratified, so each label and stratum keeps its share in both parts. It depends only on
the items and the seed, so it can be checked again at any time, and the test split stays sealed.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence

from tessera.evaluation.items import EvalItem, Split

#: Parts in ten, so the count stays exact however many small strata there are.
DEV_TENTHS = 3
DEV_SHARE = DEV_TENTHS / 10


def _group(item: EvalItem) -> tuple[str, str]:
    return item.gold_label.value, item.stratum or ",".join(sorted(item.factors))


def _position(item: EvalItem, seed: int) -> str:
    """An order that does not move when another item is added or removed."""
    return hashlib.sha256(f"{seed}:{item.item_id}".encode()).hexdigest()


def assign_splits(items: Sequence[EvalItem], *, seed: int) -> list[EvalItem]:
    groups: dict[tuple[str, str], list[EvalItem]] = defaultdict(list)
    for item in items:
        groups[_group(item)].append(item)
    assigned: list[EvalItem] = []
    carried = 0
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda item: _position(item, seed))
        # A small stratum cannot give up a fraction of an item, so the remainder carries over.
        take, carried = divmod(len(members) * DEV_TENTHS + carried, 10)
        for index, item in enumerate(members):
            split = Split.DEV if index < take else Split.TEST
            assigned.append(item.model_copy(update={"split": split}))
    return assigned


def of_split(items: Sequence[EvalItem], split: Split) -> list[EvalItem]:
    return [item for item in items if item.split is split]

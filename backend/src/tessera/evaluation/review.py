"""Human review of labels (§11.2 B, step 4).

Annotators work from a sheet that shows the message and nothing else, in an order of their own, so
they cannot see the intended label or lean on a neighbour. Agreement is then measured, and every
disagreement is settled by discussion. If one person is available, they label everything twice, at
least two weeks apart, and the agreement between their passes is what gets reported.

A model may flag an item for a second look. It never sets a label.
"""

from __future__ import annotations

import csv
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tessera.evaluation.items import EvalItem
from tessera.evaluation.statistics import cohen_kappa
from tessera.protocol.common import ResultCode

SHEET_COLUMNS = ("item_id", "message", "label", "note")
MIN_DAYS_BETWEEN_PASSES = 14
TARGET_KAPPA = 0.8


def export_sheet(items: Sequence[EvalItem], path: Path, *, annotator: str, seed: int) -> Path:
    """A blind sheet for one annotator. No label, factor, stratum or origin appears on it."""
    ordered = list(items)
    random.Random(f"{seed}:{annotator}").shuffle(ordered)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHEET_COLUMNS)
        for item in ordered:
            writer.writerow((item.item_id, item.text, "", ""))
    return path


def read_sheet(path: Path) -> dict[str, ResultCode]:
    """Labels from a filled sheet. A blank or unknown label stops the import, with its item."""
    labels: dict[str, ResultCode] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                labels[row["item_id"]] = ResultCode(row["label"].strip().upper())
            except ValueError as exc:
                raise ValueError(f"item {row['item_id']}: bad label {row['label']!r}") from exc
    return labels


@dataclass(frozen=True)
class Agreement:
    items: int
    kappa: float
    meets_target: bool
    disagreements: tuple[str, ...]
    #: Items where the annotators agree with each other but not with the policy's label.
    against_policy: tuple[str, ...]


def compare_labels(
    first: Mapping[str, ResultCode],
    second: Mapping[str, ResultCode],
    gold: Mapping[str, ResultCode],
) -> Agreement:
    """Agreement between two annotators, or two passes by one person."""
    shared = sorted(set(first) & set(second))
    kappa = cohen_kappa([first[i].value for i in shared], [second[i].value for i in shared])
    return Agreement(
        items=len(shared),
        kappa=kappa,
        meets_target=kappa >= TARGET_KAPPA,
        disagreements=tuple(i for i in shared if first[i] is not second[i]),
        against_policy=tuple(
            i for i in shared if first[i] is second[i] and i in gold and first[i] is not gold[i]
        ),
    )


def passes_far_enough_apart(first: date, second: date) -> bool:
    """The fallback for one annotator only counts if the first pass has been forgotten."""
    return (second - first).days >= MIN_DAYS_BETWEEN_PASSES


def settle(
    items: Sequence[EvalItem], settled: Mapping[str, ResultCode | None]
) -> tuple[list[EvalItem], list[str]]:
    """Apply what discussion settled. ``None`` drops an ambiguous item, and each is listed."""
    kept: list[EvalItem] = []
    dropped: list[str] = []
    for item in items:
        if item.item_id not in settled:
            kept.append(item)
        elif (label := settled[item.item_id]) is None:
            dropped.append(item.item_id)
        else:
            kept.append(item.model_copy(update={"gold_label": label}))
    return kept, dropped

"""Evaluation items, and the files that hold them (§11.2).

An item carries its gold label, but a system never sees the item: it sees :meth:`EvalItem.offer`,
which is built from the text alone. Gold labels are joined back only when results are scored, so a
run's records hold no gold either.

Dataset files stay local (see ``datasets/README.md``). An item holding a DFSA value may be written
only under a ``restricted`` folder, and :func:`write_items` refuses anywhere else.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tessera.errors import PolicyError
from tessera.governance.synthetic_gate import Channel, OfferInput
from tessera.protocol.common import ResultCode

Origin = Literal["entity_card", "template", "paraphrase", "human"]


class Level(StrEnum):
    """The two evaluations. They answer different questions, and are never pooled."""

    ENTITY = "entity"
    MESSAGE = "message"


class Split(StrEnum):
    DEV = "dev"
    TEST = "test"


class EvalItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    level: Level
    text: str
    gold_label: ResultCode
    origin: Origin
    channel: Channel | None = None
    gold_reasons: tuple[str, ...] = ()
    gold_relevant: tuple[str, ...] = ()
    #: The contact details the item was built with, to check extraction against (§11.2 C).
    contacts: tuple[str, ...] = ()
    #: E1 to E11 for an entity card (§11.2 A).
    stratum: str = ""
    #: F1 to F15 for a message (§11.2 B).
    factors: tuple[str, ...] = ()
    scenario_id: str = ""
    generator: str = ""
    synthetic: Literal[True] = True
    #: Built from DFSA facts, so it may live only in ``datasets/restricted/``.
    restricted: bool = False
    split: Split | None = None

    def offer(self) -> OfferInput:
        """What a system under test receives. No gold field can reach a case from here."""
        return OfferInput(
            text=self.text, synthetic=True, corpus_item_id=self.item_id, channel=self.channel
        )


def write_atomic(path: Path, text: str) -> None:
    """A crash leaves the old file or the new one, never half of either."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, path)


def guard_restricted(path: Path, items: Iterable[EvalItem]) -> None:
    """Anything holding a DFSA value may be written only under a ``restricted`` folder."""
    if any(item.restricted for item in items) and "restricted" not in path.parts:
        raise PermissionError(f"items holding DFSA values belong in datasets/restricted/: {path}")


def write_items(path: Path, items: Iterable[EvalItem]) -> list[EvalItem]:
    """Write items as JSON lines. Refuses a restricted item outside a restricted folder."""
    listed = list(items)
    guard_restricted(path, listed)
    known = [item.item_id for item in listed]
    if len(set(known)) != len(known):
        raise ValueError(
            f"item IDs repeat: a run keeps one record per ID, so {path} would lose some"
        )
    lines = (item.model_dump_json(exclude_defaults=False) for item in listed)
    write_atomic(path, "".join(f"{line}\n" for line in lines))
    return listed


def read_items(path: Path) -> list[EvalItem]:
    if not path.is_file():
        found = sorted(str(p) for p in path.glob("*/items.jsonl")) if path.is_dir() else []
        hint = f" Inside that folder: {', '.join(found)}." if found else ""
        raise PolicyError(f"no item file at {path}.{hint}")
    lines = path.read_text(encoding="utf-8").splitlines()
    return [EvalItem.model_validate_json(line) for line in lines if line.strip()]


def content_hash(items: Iterable[EvalItem]) -> str:
    """A hash of what the items say, whatever their order. A frozen set is compared by this."""
    lines = sorted(
        json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        for item in items
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

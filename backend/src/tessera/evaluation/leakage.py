"""Leakage controls (§11.2 D).

A prompt or rule card that names a test firm would let a system recognise the answer. This scan
looks for every name in the loaded records across all the text a system is given.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from tessera.evaluation.firms import World

#: Short names match ordinary words, and tell us nothing.
_SHORTEST_NAME = 6


def names_in(world: World) -> set[str]:
    names = {firm.name for firm in world.firms} | {firm.short_name for firm in world.firms}
    names |= {entry.name for entry in world.listed if entry.name}
    return {name for name in names if len(name) >= _SHORTEST_NAME}


def scan(world: World, folders: Iterable[Path]) -> list[str]:
    """Each place a record's name appears in text a system is given."""
    names = sorted(names_in(world), key=str.casefold)
    found: list[str] = []
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            if path.suffix not in {".md", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8").casefold()
            found += [f"{path.name}: {name}" for name in names if name.casefold() in text]
    return found

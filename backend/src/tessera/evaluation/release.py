"""The release check: the data-governance checklist, done by machine (§12.7, §17.5).

Before anything is shared, every file in it is checked for what must not leave this machine:

* files that stay local: anything under a ``restricted`` folder, run logs, ``.env``, ``PS.md`` and
  register data;
* the restricted-content marker, any DFSA deep link and any API key, by the commit guard's rules;
* any DFSA value loaded from the hand records, wherever it appears;
* any VARA fact: a name, licence reference or domain from its register or list. VARA's terms bar
  redistribution, so a message built from its facts is not released;
* any item marked restricted, and any entity-level item, which is released only as a recipe.

A file that is not text cannot be read here, so it is listed to be checked by eye. A pass does not
replace reading the checklist in docs/data-governance.md; it catches what a person can miss.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from tessera.evaluation.firms import World
from tessera.governance.masking import RestrictedValue

#: Names this short match ordinary words, and say nothing.
_SHORTEST_NAME = 6
_LOCAL_NAMES = {"PS.md", ".env"}
_LOG_SUFFIXES = {".sqlite", ".db", ".sqlite-wal", ".sqlite-shm", ".partial"}
_DATA_FOLDERS = {"inbox", "snapshots", "handrecords"}
_VARA_SOURCES = {"vara_register", "vara_unlicensed"}


@dataclass(frozen=True)
class ReleaseCheck:
    files: int
    problems: tuple[str, ...]
    #: Files that are not text, so nothing here could read them.
    by_eye: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.problems


def load_guard(root: Path) -> ModuleType:
    """The commit guard's rules, loaded from the script itself so they are never copied."""
    spec = importlib.util.spec_from_file_location(
        "check_restricted", root / "scripts" / "check_restricted.py"
    )
    if spec is None or spec.loader is None:
        raise FileNotFoundError("scripts/check_restricted.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vara_facts(world: World) -> set[str]:
    """Every VARA name, licence reference and domain on record."""
    facts: set[str] = set()
    for firm in world.of("VARA"):
        facts |= {firm.name, firm.short_name, firm.reference or "", firm.domain or ""}
    for entry in world.listed:
        if entry.source_id in _VARA_SOURCES:
            facts |= {entry.name or "", *entry.contacts}
    return {fact for fact in facts if len(fact) >= _SHORTEST_NAME}


def _path_problems(relative: Path) -> list[str]:
    name = relative.name
    found = []
    if "restricted" in relative.parts:
        found.append("it is under a restricted folder")
    if name in _LOCAL_NAMES or (name.startswith(".env.") and name != ".env.example"):
        found.append("this file stays local")
    if relative.suffix in _LOG_SUFFIXES:
        found.append("a run log or event store")
    if _DATA_FOLDERS & set(relative.parts):
        found.append("register data")
    return found


def _item_problems(text: str) -> list[str]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("restricted"):
            found.append(f"line {number}: an item built from DFSA facts")
        if item.get("level") == "entity":
            found.append(f"line {number}: an entity-level item, which ships only as a recipe")
        if item.get("synthetic") is not True:
            found.append(f"line {number}: an item not marked synthetic")
    return found


def check_release(
    paths: Sequence[Path],
    *,
    root: Path,
    restricted: Iterable[RestrictedValue],
    vara: set[str],
) -> ReleaseCheck:
    """Check every file under ``paths``. Nothing is changed."""
    guard = load_guard(root)
    dfsa = sorted({v.value for v in restricted if len(v.value) >= 4}, key=str.casefold)
    vara_sorted = sorted(vara, key=str.casefold)
    files: list[tuple[Path, Path]] = []
    for path in paths:
        if path.is_dir():
            files += [(f, f.relative_to(path)) for f in sorted(path.rglob("*")) if f.is_file()]
        else:
            files.append((path, Path(path.name)))
    problems: list[str] = []
    by_eye: list[str] = []
    for file, relative in files:
        shown = relative.as_posix()
        problems += [f"{shown}: {reason}" for reason in _path_problems(relative)]
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            by_eye.append(shown)
            continue
        # The guard names the file itself, and catches the marker, DFSA deep links and keys.
        problems += guard.check_content(shown, text)
        folded = text.casefold()
        problems += [
            f"{shown}: a DFSA value ({len(value)} characters)"
            for value in dfsa
            if value.casefold() in folded
        ]
        problems += [
            f"{shown}: a VARA fact, {fact!r}" for fact in vara_sorted if fact.casefold() in folded
        ]
        if relative.name == "items.jsonl" or relative.suffix == ".jsonl":
            problems += [f"{shown}: {reason}" for reason in _item_problems(text)]
    return ReleaseCheck(len(files), tuple(dict.fromkeys(problems)), tuple(by_eye))

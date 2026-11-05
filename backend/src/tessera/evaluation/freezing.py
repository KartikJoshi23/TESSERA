"""Fixing what a result rests on, so it cannot change unnoticed.

A freeze records a finished set with everything a system is given. A test split may run only against
a freeze that still matches (§11.2 D), so tuning cannot touch sealed data, and neither the items nor
the prompts can change after it.

A run takes many sessions, and it pins the same things when it starts. Going on with different
prompts, a different thinking setting or another date would pool results that are not comparable,
so a session that differs is refused. A new configuration gets a new run folder.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from tessera.config.settings import Settings
from tessera.evaluation.items import EvalItem, content_hash, write_atomic
from tessera.llm.config import ModelsPolicy

RUN_FILE = "run.json"


def _tree_hash(folders: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for folder in folders:
        for path in sorted(item for item in folder.rglob("*") if item.is_file()):
            if "__pycache__" not in path.parts:
                digest.update(path.relative_to(folder).as_posix().encode("utf-8"))
                digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def fingerprint(settings: Settings, models: ModelsPolicy) -> dict[str, str]:
    """Everything a system is given. The pace is left out: it changes no answer."""
    settings_of_models = models.model_dump(mode="json", exclude={"rate_limit"})
    text = json.dumps(settings_of_models, sort_keys=True)
    plan = settings.root / "eval" / "plan.yaml"
    return {
        "plan": hashlib.sha256(plan.read_bytes()).hexdigest()[:16],
        "prompts": _tree_hash([settings.root / "backend" / "prompts"]),
        "policies": _tree_hash([settings.policies_dir]),
        "knowledge": _tree_hash([settings.knowledge_dir]),
        "models": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    }


def freeze_manifest(items: Sequence[EvalItem], print_: dict[str, str]) -> dict[str, Any]:
    return {
        "items": len(items),
        "hash": content_hash(items),
        "levels": sorted({item.level.value for item in items}),
        "fingerprint": print_,
    }


def _changed(before: dict[str, str], now: dict[str, str]) -> list[str]:
    return [name for name in sorted(now) if before.get(name) != now[name]]


def frozen_problems(
    manifest: dict[str, Any], items: Sequence[EvalItem], print_: dict[str, str]
) -> list[str]:
    """Why these items may not run as frozen. Empty means they may."""
    problems = []
    if manifest["hash"] != content_hash(items):
        problems.append("the items differ from the frozen set")
    problems += [
        f"{name} changed since the freeze" for name in _changed(manifest["fingerprint"], print_)
    ]
    return problems


def pin_run(
    run_dir: Path, print_: dict[str, str], today: date, *, stated: date | None = None
) -> tuple[date, list[str]]:
    """The date a run reads records as of, and why this session may not go on with it, if so.

    The first session fixes both. A run takes weeks, and a date that moved with the calendar could
    cross a snapshot's age limit part way, so later conditions would see a different world.
    """
    path = run_dir / RUN_FILE
    if not path.exists():
        chosen = stated or today
        write_atomic(
            path,
            json.dumps({"fingerprint": print_, "today": chosen.isoformat()}, indent=1) + "\n",
        )
        return chosen, []
    pinned = json.loads(path.read_text(encoding="utf-8"))
    chosen = date.fromisoformat(pinned["today"])
    problems = [
        f"{name} changed since this run began" for name in _changed(pinned["fingerprint"], print_)
    ]
    if stated is not None and stated != chosen:
        problems.append(f"this run reads records as of {chosen}, not {stated}")
    return chosen, problems

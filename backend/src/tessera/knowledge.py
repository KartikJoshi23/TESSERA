"""Loaders for ``knowledge/``: rule cards (our own wording, with citations) and the activity
taxonomy. Rule cards are validated so that no citation can carry a DFSA deep link.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from tessera.errors import PolicyError
from tessera.governance.links import find_dfsa_deep_links

RuleStatus = Literal[
    "verified_primary", "verified_secondary", "needs_verification", "design_principle"
]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleSource(_Frozen):
    title: str
    url: str | None = None
    accessed: date | None = None
    note: str | None = None

    @field_validator("url")
    @classmethod
    def _no_dfsa_deep_link(cls, value: str | None) -> str | None:
        if value and find_dfsa_deep_links(value):
            raise ValueError("DFSA sources may be cited by homepage only (https://www.dfsa.ae/)")
        return value


class RuleCard(_Frozen):
    id: str
    regulator: str
    statement: str
    applies_when: tuple[str, ...]
    effect: str
    status: RuleStatus
    sources: tuple[RuleSource, ...]
    last_reviewed: date

    @model_validator(mode="after")
    def _cited(self) -> RuleCard:
        if self.status != "design_principle" and not self.sources:
            raise ValueError(f"{self.id}: every non-principle rule needs at least one source")
        return self


class Activity(_Frozen):
    code: str
    group: str
    label: str
    keywords: tuple[str, ...]
    #: Words that show a recorded DFSA service covers this activity. Our own mapping, lower-case.
    dfsa_terms: tuple[str, ...] = ()


class ActivityTaxonomy(_Frozen):
    version: int
    groups: dict[str, str]
    activities: tuple[Activity, ...]
    #: A recorded DFSA service with one of these words is left unmapped, so scope stays unknown.
    dfsa_unclear_terms: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> ActivityTaxonomy:
        codes = [a.code for a in self.activities]
        if len(codes) != len(set(codes)):
            raise ValueError("activity codes must be unique")
        if unknown := {a.group for a in self.activities} - set(self.groups):
            raise ValueError(f"unknown activity groups: {sorted(unknown)}")
        return self

    def dfsa_scope(self, services: Iterable[str]) -> tuple[list[str], bool]:
        """The activity codes recorded DFSA services cover, and whether the list is complete.

        Models see this result, never the recorded services (implementation-plan.md §6.9). The
        list is complete only if services were recorded and every one of them was understood. If
        it is not complete, an activity that is missing from the list has unknown scope.
        """
        covered: set[str] = set()
        recorded = [service.casefold() for service in services]
        complete = bool(recorded)
        for service in recorded:
            codes = {
                activity.code
                for activity in self.activities
                if any(term in service for term in activity.dfsa_terms)
            }
            if not codes or any(term in service for term in self.dfsa_unclear_terms):
                complete = False
                continue
            covered |= codes
        return sorted(covered), complete


def _yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PolicyError(f"{path.name} must contain a mapping")
    return data


@lru_cache(maxsize=8)
def load_rule_cards(knowledge_dir: Path) -> dict[str, RuleCard]:
    cards: dict[str, RuleCard] = {}
    for path in sorted((knowledge_dir / "rule_cards").glob("*.yaml")):
        for body in _yaml(path).get("rules") or []:
            try:
                card = RuleCard(**body)
            except ValidationError as exc:
                raise PolicyError(f"invalid rule card in {path.name}:\n{exc}") from exc
            if card.id in cards:
                raise PolicyError(f"duplicate rule card id {card.id} in {path.name}")
            cards[card.id] = card
    if not cards:
        raise PolicyError(f"no rule cards found in {knowledge_dir / 'rule_cards'}")
    return cards


@lru_cache(maxsize=8)
def load_activity_taxonomy(knowledge_dir: Path) -> ActivityTaxonomy:
    try:
        return ActivityTaxonomy(**_yaml(knowledge_dir / "taxonomy" / "activities.yaml"))
    except ValidationError as exc:
        raise PolicyError(f"invalid activity taxonomy:\n{exc}") from exc

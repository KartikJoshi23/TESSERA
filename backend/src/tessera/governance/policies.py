"""Load and validate the machine-readable policies in ``policies/``.

The loaders check structure *and* the safety invariants the rest of the code relies on, so a
mistaken edit to a YAML file fails loudly instead of silently weakening a rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from tessera.errors import PolicyError

UAE_REGULATORS = frozenset({"CMA", "DFSA", "VARA", "CBUAE", "FSRA"})
OUTCOME_CODES = ("CONSISTENT", "CONFLICTS", "UNVERIFIED")
ContactRoleName = Literal["deciding", "reported", "not_comparable"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- sources.yaml


class SourcePolicy(_Frozen):
    """Access, storage and linking rules for one data source."""

    id: str
    name: str
    regulator: str
    phase: Literal[1, 2, "optional"]
    enabled: bool
    access_method: Literal["manual_export", "hand_record", "manual_download", "api"]
    automated_access: bool
    storage: Literal["snapshot", "restricted_facts", "none"]
    restricted: bool
    homepage: str
    page_url: str | None = None
    deep_links_allowed: bool
    framing_allowed: bool = False
    public_release: Literal["never", "rehydration_only", "with_permission", "allowed"]
    attribution: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _invariants(self) -> SourcePolicy:
        problems: list[str] = []
        if self.regulator in UAE_REGULATORS:
            if self.automated_access:
                problems.append("UAE regulator sources must not allow automated access")
            if self.framing_allowed:
                problems.append("regulator pages must never be framed")
        if self.restricted:
            if self.storage != "restricted_facts":
                problems.append("restricted sources store hand-recorded facts only")
            if self.deep_links_allowed or self.page_url is not None:
                problems.append("restricted sources link to their homepage only")
            if self.public_release not in {"never", "with_permission"}:
                problems.append("restricted sources are never released without permission")
        if problems:
            raise ValueError(f"{self.id}: " + "; ".join(problems))
        return self


class NetworkPolicy(_Frozen):
    deny_automated_domains: tuple[str, ...]
    allowed_llm_hosts: tuple[str, ...]

    @field_validator("deny_automated_domains", "allowed_llm_hosts")
    @classmethod
    def _normalise(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip().lower().rstrip(".") for item in value)


class SourcesPolicy(_Frozen):
    version: int
    network: NetworkPolicy
    sources: dict[str, SourcePolicy]

    @model_validator(mode="after")
    def _regulator_homepages_are_denied(self) -> SourcesPolicy:
        deny = self.network.deny_automated_domains
        for source in self.sources.values():
            if source.regulator not in UAE_REGULATORS:
                continue
            host = (urlsplit(source.homepage).hostname or "").lower()
            if not any(host == d or host.endswith("." + d) for d in deny):
                raise ValueError(f"{source.id}: {host} is missing from deny_automated_domains")
        return self

    def source(self, source_id: str) -> SourcePolicy:
        try:
            return self.sources[source_id]
        except KeyError:
            raise PolicyError(f"unknown source {source_id!r}") from None


# --------------------------------------------------------------------------- language_policy.yaml


class BannedTerm(_Frozen):
    pattern: str
    category: Literal["verdict", "advice"]
    note: str = ""

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {value!r}: {exc}") from exc
        return value


class LanguagePolicy(_Frozen):
    version: int
    result_strings: dict[str, str]
    disclaimer: str
    banned_terms: tuple[BannedTerm, ...]
    allowed_phrases: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _all_outcomes(self) -> LanguagePolicy:
        if set(self.result_strings) != set(OUTCOME_CODES):
            raise ValueError(f"result_strings must define exactly {OUTCOME_CODES}")
        return self


# --------------------------------------------------------------------------- decision_policy.yaml


class PolicyRule(_Frozen):
    id: str
    text: str


class Thresholds(_Frozen):
    staleness_days: int
    name_fuzzy_tau1: float
    name_partial_tau2: float
    partial_min_length: int
    lookalike_max_edit_distance: int
    lookalike_min_similarity: float
    lookalike_min_brand_length: int


class DecisionPolicy(_Frozen):
    version: int
    outcomes: dict[str, str]
    hard_conflicts: tuple[PolicyRule, ...]
    consistent_conditions: tuple[PolicyRule, ...]
    unverified_reasons: tuple[PolicyRule, ...]
    precedence: tuple[PolicyRule, ...]
    regulator_names: dict[str, tuple[str, ...]]
    contact_roles: dict[str, ContactRoleName]
    thresholds: Thresholds

    @model_validator(mode="after")
    def _complete(self) -> DecisionPolicy:
        expected = {
            "hard_conflicts": [f"HC{i}" for i in range(1, 7)],
            "consistent_conditions": [f"K{i}" for i in range(1, 8)],
            "unverified_reasons": [f"U{i}" for i in range(1, 10)],
            "precedence": [f"P{i}" for i in range(1, 8)],
        }
        for field_name, ids in expected.items():
            found = [rule.id for rule in getattr(self, field_name)]
            if found != ids:
                raise ValueError(f"{field_name} must list {ids} in order, found {found}")
        if set(self.outcomes) != set(OUTCOME_CODES):
            raise ValueError(f"outcomes must define exactly {OUTCOME_CODES}")
        if set(self.regulator_names) != UAE_REGULATORS:
            raise ValueError(f"regulator_names must cover exactly {sorted(UAE_REGULATORS)}")
        return self


# --------------------------------------------------------------------------- loaders


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise PolicyError(f"missing policy file: {path}") from exc
    except yaml.YAMLError as exc:
        raise PolicyError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"{path.name} must contain a mapping")
    return data


@lru_cache(maxsize=16)
def load_sources_policy(policies_dir: Path) -> SourcesPolicy:
    data = _read_yaml(policies_dir / "sources.yaml")
    sources = {
        sid: {**(body or {}), "id": sid} for sid, body in (data.get("sources") or {}).items()
    }
    try:
        return SourcesPolicy(
            version=data.get("version"), network=data.get("network"), sources=sources
        )
    except ValidationError as exc:
        raise PolicyError(f"invalid policies/sources.yaml:\n{exc}") from exc


@lru_cache(maxsize=16)
def load_language_policy(policies_dir: Path) -> LanguagePolicy:
    try:
        return LanguagePolicy(**_read_yaml(policies_dir / "language_policy.yaml"))
    except ValidationError as exc:
        raise PolicyError(f"invalid policies/language_policy.yaml:\n{exc}") from exc


@lru_cache(maxsize=16)
def load_decision_policy(policies_dir: Path) -> DecisionPolicy:
    try:
        return DecisionPolicy(**_read_yaml(policies_dir / "decision_policy.yaml"))
    except ValidationError as exc:
        raise PolicyError(f"invalid policies/decision_policy.yaml:\n{exc}") from exc


@dataclass(frozen=True)
class Policies:
    """All three policies, loaded together."""

    sources: SourcesPolicy
    language: LanguagePolicy
    decision: DecisionPolicy


def load_policies(policies_dir: Path) -> Policies:
    return Policies(
        sources=load_sources_policy(policies_dir),
        language=load_language_policy(policies_dir),
        decision=load_decision_policy(policies_dir),
    )

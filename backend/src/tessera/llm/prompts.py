"""Versioned prompts. Files live in ``backend/prompts/<version>/``.

A system prompt is built from fixed parts only, so it is byte-identical across cases. Its hash is
recorded on every case, which ties each result to the exact prompt text that produced it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tessera.errors import PolicyError
from tessera.governance.policies import DecisionPolicy, PolicyRule
from tessera.knowledge import ActivityTaxonomy, RuleCard

DEFAULT_VERSION = "v1"


@dataclass(frozen=True)
class RenderedPrompt:
    text: str
    sha256: str


def render_rule_cards(cards: Iterable[RuleCard]) -> str:
    lines = ["## Rule cards", "Cite rules by their ID. Only rules listed here exist."]
    for card in cards:
        note = "" if card.status == "verified_primary" else f" (status: {card.status})"
        lines.append(f"- [{card.id}] {' '.join(card.statement.split())}{note}")
    return "\n".join(lines)


def render_activities(taxonomy: ActivityTaxonomy) -> str:
    lines = ["## Activity codes", "Use only these codes."]
    lines += [f"- {a.code}: {a.label}" for a in taxonomy.activities]
    return "\n".join(lines)


def render_decision_policy(policy: DecisionPolicy) -> str:
    def section(title: str, rules: Iterable[PolicyRule]) -> list[str]:
        return [f"### {title}", *(f"- {rule.id}: {rule.text}" for rule in rules)]

    lines = ["## Decision policy"]
    lines += section("Hard conflicts (any one gives CONFLICTS)", policy.hard_conflicts)
    lines += section("Conditions for CONSISTENT (all required)", policy.consistent_conditions)
    lines += section("Reasons for UNVERIFIED", policy.unverified_reasons)
    lines += section("Precedence rules for resolving conflicts", policy.precedence)
    return "\n".join(lines)


class PromptLibrary:
    def __init__(self, directory: Path, version: str = DEFAULT_VERSION) -> None:
        self.version = version
        self.directory = directory / version

    def read(self, name: str) -> str:
        path = self.directory / f"{name}.md"
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise PolicyError(f"missing prompt file: {path}") from exc

    def build(self, *parts: str) -> RenderedPrompt:
        """Join prompt parts. Each is a file name, or literal text if it spans several lines."""
        sections = [part if "\n" in part else self.read(part) for part in parts]
        text = "\n\n".join(sections) + "\n"
        return RenderedPrompt(text, hashlib.sha256(text.encode("utf-8")).hexdigest())

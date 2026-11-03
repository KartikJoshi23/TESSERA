"""Deterministic language linter for user-facing results (Verifier gate G5).

Bans verdict words ("scam", "clone" …) and advice ("you should invest" …) defined in
``policies/language_policy.yaml``. Allowed proper nouns such as "Anti-Fraud Center" are blanked
out before scanning, so they never trigger a violation.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from tessera.governance.policies import LanguagePolicy


class LanguageViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    term: str
    category: str
    start: int
    end: int
    pattern: str


def _blank_allowed_phrases(text: str, phrases: tuple[str, ...]) -> str:
    for phrase in phrases:
        text = re.sub(re.escape(phrase), lambda m: " " * len(m.group(0)), text, flags=re.IGNORECASE)
    return text


def lint_text(text: str, policy: LanguagePolicy) -> list[LanguageViolation]:
    """Return every banned verdict or advice term in ``text``, in order of appearance."""
    scan = _blank_allowed_phrases(text, policy.allowed_phrases)
    violations = [
        LanguageViolation(
            term=text[m.start() : m.end()],
            category=term.category,
            start=m.start(),
            end=m.end(),
            pattern=term.pattern,
        )
        for term in policy.banned_terms
        for m in re.finditer(term.pattern, scan, flags=re.IGNORECASE)
    ]
    return sorted(violations, key=lambda v: (v.start, v.end))


def has_disclaimer(text: str, policy: LanguagePolicy) -> bool:
    """True if the standard disclaimer appears in ``text`` (whitespace-insensitive)."""
    return " ".join(policy.disclaimer.split()) in " ".join(text.split())

"""Restricted-value masking gateway (implementation-plan.md §9.4, requirement R21).

Before any request leaves the machine, every restricted value is replaced with a stable
placeholder such as ``⟦R:FIRM-1⟧``. Restricted values are DFSA firm names, reference numbers,
domains, emails and phone numbers.

* Generic parts of firm names stay visible: ``"Lumen Crest Capital (DIFC) Limited"`` becomes
  ``"⟦R:FIRM-1⟧ (DIFC) Limited"``.
* Placeholders are numbered deterministically, so the same inputs always mask the same way.
* Placeholders are restored only locally (:meth:`MaskingGateway.unmask`).
* :meth:`MaskingGateway.leaked_values` powers the invariant test that no restricted value appears
  in any outgoing payload.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from tessera.normalize.domains import domain_parts
from tessera.normalize.names import normalize_name
from tessera.normalize.phones import normalize_phone

ValueKind = Literal["firm_name", "domain", "email", "phone", "reference"]

_PREFIX: dict[str, str] = {
    "firm_name": "FIRM",
    "domain": "DOMAIN",
    "email": "EMAIL",
    "phone": "PHONE",
    "reference": "REF",
}
_PLACEHOLDER = re.compile("(⟦R:[A-Z]+-\\d+⟧)")  # ⟦R:KIND-n⟧
_SEP = r"[\s\-_.]*"
_PHONE_SEP = r"[\s\-().]*"
#: Single-token names shorter than this are too generic to mask on their own.
_MIN_SINGLE_TOKEN_CORE = 6


@dataclass(frozen=True)
class RestrictedValue:
    value: str
    kind: ValueKind
    source_ref: str = ""  # restricted row ID, for audit


@dataclass(frozen=True)
class _Rule:
    placeholder: str
    canonical: str
    pattern: re.Pattern[str]


def classify_value(value: str) -> ValueKind | None:
    """Guess the kind of a contact value recorded in an alert (email, domain or phone)."""
    text = value.strip()
    if not text:
        return None
    if "@" in text and not text.startswith("@"):
        return "email"
    if text.startswith("@"):
        return "domain" if domain_parts(text[1:]) else None
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 7 and len(digits) >= 0.6 * len(re.sub(r"\s", "", text)):
        return "phone"
    if domain_parts(text):
        return "domain"
    return "reference" if len(text) >= 4 else None


def _name_rule(value: str) -> tuple[str, str, re.Pattern[str]] | None:
    tokens = normalize_name(value).core_tokens
    if not tokens:
        return None
    core = " ".join(tokens)
    if len(tokens) == 1 and len(core) < _MIN_SINGLE_TOKEN_CORE:
        return "firm_name", value, re.compile(re.escape(value), re.IGNORECASE)
    body = _SEP.join(re.escape(token) for token in tokens)
    return "firm_name", core, re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def _domain_rule(value: str) -> tuple[str, str, re.Pattern[str]] | None:
    parts = domain_parts(value)
    if parts is None:
        return None
    canonical = parts.registrable
    return "domain", canonical, re.compile(rf"(?<![\w\-]){re.escape(canonical)}(?![\w\-])", re.I)


def _email_rule(value: str) -> tuple[str, str, re.Pattern[str]] | None:
    text = value.strip().lower()
    if text.startswith("@"):
        return _domain_rule(text[1:])
    if "@" not in text:
        return None
    return "email", text, re.compile(rf"(?<![\w.+\-]){re.escape(text)}(?![\w\-])", re.IGNORECASE)


def _phone_rule(value: str) -> tuple[str, str, re.Pattern[str]] | None:
    info = normalize_phone(value)
    if info is None:
        return None
    country = str(info.country_code)
    national = info.e164[1 + len(country) :]
    digits = _PHONE_SEP.join(national)
    prefix = rf"(?:(?:\+|00){country}{_PHONE_SEP}|0{_PHONE_SEP})?"
    return "phone", info.e164, re.compile(rf"(?<!\d){prefix}{digits}(?!\d)")


def _reference_rule(value: str) -> tuple[str, str, re.Pattern[str]] | None:
    text = value.strip()
    if len(text) < 4:
        return None
    return "reference", text, re.compile(rf"(?<!\w){re.escape(text)}(?!\w)", re.IGNORECASE)


_BUILDERS = {
    "firm_name": _name_rule,
    "domain": _domain_rule,
    "email": _email_rule,
    "phone": _phone_rule,
    "reference": _reference_rule,
}


class MaskingGateway:
    """Masks a fixed set of restricted values in text and nested payloads."""

    def __init__(self, values: Iterable[RestrictedValue]) -> None:
        counters: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        rules: list[_Rule] = []
        for item in sorted(set(values), key=lambda v: (v.kind, v.value.casefold())):
            built = _BUILDERS[item.kind](item.value)
            if built is None:
                continue
            kind, canonical, pattern = built
            key = (kind, canonical.casefold())
            if key in seen:
                continue
            seen.add(key)
            prefix = _PREFIX[kind]
            counters[prefix] = counters.get(prefix, 0) + 1
            placeholder = f"⟦R:{prefix}-{counters[prefix]}⟧"
            rules.append(_Rule(placeholder, canonical, pattern))
        # Longest values first, so a domain is replaced before a name that it contains.
        self._rules = sorted(rules, key=lambda r: (-len(r.canonical), r.placeholder))
        self._canonical = {rule.placeholder: rule.canonical for rule in rules}

    @property
    def placeholders(self) -> dict[str, str]:
        """Placeholder → canonical value (local use only; never send this mapping out)."""
        return dict(self._canonical)

    def __len__(self) -> int:
        return len(self._rules)

    def mask(self, text: str) -> str:
        for rule in self._rules:
            pieces = _PLACEHOLDER.split(text)
            # Even indices are ordinary text; odd indices are existing placeholders.
            text = "".join(
                piece if i % 2 else rule.pattern.sub(rule.placeholder, piece)
                for i, piece in enumerate(pieces)
            )
        return text

    def unmask(self, text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: self._canonical.get(m.group(1), m.group(1)), text)

    def mask_payload(self, payload: Any) -> Any:
        """Recursively mask every string in a JSON-like payload (dicts, lists, tuples)."""
        return _map_strings(payload, self.mask)

    def unmask_payload(self, payload: Any) -> Any:
        return _map_strings(payload, self.unmask)

    def leaked_values(self, text: str) -> list[str]:
        """Restricted values still present in ``text``. Empty means the text is safe to send."""
        # Join the non-placeholder segments with NUL so no pattern can match across a boundary.
        outside = "\x00".join(_PLACEHOLDER.split(text)[0::2])
        return [rule.canonical for rule in self._rules if rule.pattern.search(outside)]


def _map_strings(payload: Any, func: Any) -> Any:
    if isinstance(payload, str):
        return func(payload)
    if isinstance(payload, dict):
        return {key: _map_strings(value, func) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_map_strings(item, func) for item in payload]
    if isinstance(payload, tuple):
        return tuple(_map_strings(item, func) for item in payload)
    return payload

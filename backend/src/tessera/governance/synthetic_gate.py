"""Admit only clearly labelled synthetic offers, and flag real-looking personal data.

PS.md requires synthetic messages only (UAE data-protection law). The gate rejects any offer not
marked synthetic, and warns about content that looks like a real person's data: an Emirates ID,
a payment card, a personal email address, or a phone number outside the ranges reserved for
fiction.
"""

from __future__ import annotations

import re
from typing import Literal

import phonenumbers
from pydantic import BaseModel, ConfigDict, Field

from tessera.errors import SyntheticInputRejected
from tessera.normalize.phones import is_reserved_fiction

Channel = Literal["whatsapp", "telegram", "sms", "email", "social", "phone_call", "web", "other"]

_EMIRATES_ID = re.compile(r"\b784[-\s]?\d{4}[-\s]?\d{7}[-\s]?\d\b")
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_IBAN_LIKE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24})\b")
_PERSONAL_MAIL = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "mail.com",
        "yandex.com",
    }
)


class OfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=20_000)
    synthetic: bool
    corpus_item_id: str | None = None
    synthetic_attestation: bool = False
    channel: Channel | None = None


class PiiWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["emirates_id", "payment_card", "personal_email", "phone"]
    excerpt: str
    message: str


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _redact(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    return f"…{digits[-4:]}" if len(digits) >= 4 else "…"


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in spans)


def pii_warnings(text: str) -> list[PiiWarning]:
    """Warnings for content that looks like a real person's data (never raises)."""
    warnings: list[PiiWarning] = []
    id_spans = [m.span() for m in _EMIRATES_ID.finditer(text)]
    for start, end in id_spans:
        warnings.append(
            PiiWarning(
                kind="emirates_id",
                excerpt=_redact(text[start:end]),
                message="Looks like an Emirates ID number. Synthetic offers must not contain one.",
            )
        )
    skip = id_spans + [m.span() for m in _IBAN_LIKE.finditer(text)]
    for match in _CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits) and not _overlaps(match.span(), skip):
            warnings.append(
                PiiWarning(
                    kind="payment_card",
                    excerpt=_redact(match.group(0)),
                    message="Looks like a payment card number.",
                )
            )
    for match in _EMAIL.finditer(text):
        if match.group(1).lower() in _PERSONAL_MAIL:
            warnings.append(
                PiiWarning(
                    kind="personal_email",
                    excerpt=match.group(1).lower(),
                    message="A personal email address; use a reserved .example domain instead.",
                )
            )
    for found in phonenumbers.PhoneNumberMatcher(text, "AE"):
        e164 = phonenumbers.format_number(found.number, phonenumbers.PhoneNumberFormat.E164)
        if not is_reserved_fiction(e164):
            warnings.append(
                PiiWarning(
                    kind="phone",
                    excerpt=_redact(e164),
                    message=(
                        "A phone number outside the ranges reserved for fiction. Make sure it "
                        "is synthetic or an official business number from a register."
                    ),
                )
            )
    return warnings


def check_offer_input(offer: OfferInput) -> list[PiiWarning]:
    """Reject anything not marked synthetic; return warnings about real-looking personal data."""
    if not offer.synthetic:
        raise SyntheticInputRejected(
            "only synthetic offers may be processed; real messages are never used"
        )
    if not (offer.corpus_item_id or offer.synthetic_attestation):
        raise SyntheticInputRejected(
            "a synthetic offer needs a corpus item ID or an explicit synthetic attestation"
        )
    return pii_warnings(offer.text)

"""Phone-number normalisation (libphonenumber metadata bundled with ``phonenumbers``)."""

from __future__ import annotations

import re
from dataclasses import dataclass

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType

_TYPE_NAMES = {
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE: "fixed_line",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.SHARED_COST: "shared_cost",
    PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "uan",
    PhoneNumberType.VOICEMAIL: "voicemail",
}

# Ranges reserved for drama and fiction: no real subscriber can hold these numbers.
_FICTION_RANGES = (
    re.compile(r"^\+447700900\d{3}$"),  # UK (Ofcom) mobile: 07700 900000–900999
    re.compile(r"^\+442079460\d{3}$"),  # UK (Ofcom) London: 020 7946 0000–0999
    re.compile(r"^\+1\d{3}55501\d{2}$"),  # North America: NXX-555-0100–0199
)


@dataclass(frozen=True)
class PhoneInfo:
    e164: str
    country_code: int
    region: str | None
    number_type: str
    is_valid: bool


def normalize_phone(raw: str, default_region: str = "AE") -> PhoneInfo | None:
    """Parse ``raw`` (UAE by default) into E.164, or ``None`` if it is not a possible number."""
    try:
        number = phonenumbers.parse(raw, default_region)
    except NumberParseException:
        return None
    if not phonenumbers.is_possible_number(number):
        return None
    return PhoneInfo(
        e164=phonenumbers.format_number(number, PhoneNumberFormat.E164),
        country_code=number.country_code or 0,
        region=phonenumbers.region_code_for_number(number),
        number_type=_TYPE_NAMES.get(phonenumbers.number_type(number), "unknown"),
        is_valid=phonenumbers.is_valid_number(number),
    )


def is_reserved_fiction(e164: str) -> bool:
    """True for numbers in ranges reserved for fiction (safe for synthetic offers)."""
    return any(pattern.match(e164) for pattern in _FICTION_RANGES)

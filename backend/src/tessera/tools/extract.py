"""Deterministic extraction of contact points from offer text (no network, no model).

The extractor finds:

* websites and domains, emails, phone and WhatsApp numbers;
* Telegram and social handles, and short links;
* IBANs and crypto wallets;
* licence references and address cues.

Each contact point is tagged with its role (§4.7), which says whether it can decide a result.
Spans are exact offsets into the original text, so ``text[cp.start:cp.end] == cp.raw``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import phonenumbers
from schwifty import IBAN

from tessera.normalize.domains import domain_parts
from tessera.normalize.phones import normalize_phone
from tessera.protocol.contacts import (
    DEFAULT_CONTACT_ROLES,
    ContactKind,
    ContactPoint,
    ContactRole,
)

SHORT_LINK_DOMAINS = frozenset(
    {
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "ow.ly",
        "is.gd",
        "buff.ly",
        "rebrand.ly",
        "cutt.ly",
        "shorturl.at",
        "tiny.cc",
        "rb.gy",
        "s.id",
    }
)
SOCIAL_DOMAINS = frozenset(
    {
        "instagram.com",
        "facebook.com",
        "fb.com",
        "x.com",
        "twitter.com",
        "tiktok.com",
        "linkedin.com",
        "youtube.com",
        "snapchat.com",
    }
)
TELEGRAM_HOSTS = frozenset({"t.me", "telegram.me"})
WHATSAPP_HOSTS = frozenset({"wa.me", "api.whatsapp.com", "whatsapp.com"})

_TRAILING = ".,;:!?)]}'\""
_URL = re.compile(r"\bhttps?://[^\s<>\"'\])]+", re.IGNORECASE)
_EMAIL = re.compile(
    r"(?<![\w.+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}\b"
)
_LABEL = r"[^\W_](?:[\w\-]{0,61}[^\W_])?"
_DOMAIN = re.compile(rf"(?<![@\w.\-/])(?:{_LABEL}\.)+[^\W\d_]{{2,24}}(?:/[^\s<>\"'\])]*)?")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
_WALLETS = (
    ("ETH", re.compile(r"\b0x[a-fA-F0-9]{40}\b")),
    ("BTC", re.compile(r"\bbc1[ac-hj-np-z02-9]{11,71}\b")),
    ("TRON", re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")),
    ("BTC", re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")),
)
_LICENCE_REFS = (
    ("DFSA_FRN", re.compile(r"\bF\d{6}\b")),
    ("VARA_REF", re.compile(r"\b(?:VL|IPA|MVP)/\d{2}/\d{2}/\d{3}\b", re.IGNORECASE)),
    (
        "LICENCE_NO",
        re.compile(
            r"\blicen[cs]e\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-]{2,24})",
            re.IGNORECASE,
        ),
    ),
)
_HANDLE = re.compile(r"(?<![\w@.])@([A-Za-z][A-Za-z0-9_.]{2,30})(?![\w@])")
_ADDRESS_LABEL = re.compile(
    r"\b(?:office|address|located at|head office|headquarters|visit us at)\s*[:\-]?\s*"
    r"([^\n.;]{3,100})",
    re.IGNORECASE,
)
_BUILDING_CUES = (
    "gate village",
    "gate building",
    "gate district",
    "index tower",
    "emirates financial towers",
    "icd brookfield place",
    "adgm square",
    "al maryah island",
)
# Checked in order: specific zones before emirate-wide words.
_ZONE_CUES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "gate village",
            "gate building",
            "gate district",
            "index tower",
            "emirates financial towers",
            "icd brookfield",
            "dubai international financial cent",
            "difc",
        ),
        "DIFC",
    ),
    (("adgm square", "al maryah", "abu dhabi global market", "adgm"), "ADGM"),
    (
        (
            "business bay",
            "jumeirah lakes towers",
            "jlt",
            "dmcc",
            "dubai marina",
            "sheikh zayed road",
            "deira",
            "bur dubai",
            "dubai silicon oasis",
            "world trade centre",
            "dubai",
        ),
        "DUBAI_NON_DIFC",
    ),
    (
        ("sharjah", "ajman", "ras al khaimah", "fujairah", "umm al quwain", "abu dhabi"),
        "OTHER_EMIRATE",
    ),
)


def detect_zone(text: str) -> str:
    """Best-effort zone tag for an address or offer fragment."""
    lowered = text.casefold()
    for cues, zone in _ZONE_CUES:
        if any(re.search(rf"\b{re.escape(cue)}", lowered) for cue in cues):
            return zone
    return "UNKNOWN"


class _Spans:
    def __init__(self) -> None:
        self._taken: list[tuple[int, int]] = []

    def free(self, start: int, end: int) -> bool:
        return not any(start < e and s < end for s, e in self._taken)

    def take(self, start: int, end: int) -> bool:
        if not self.free(start, end):
            return False
        self._taken.append((start, end))
        return True


def _classify_link(text: str) -> tuple[ContactKind, str, dict[str, str]] | None:
    parts = domain_parts(text)
    if parts is None:
        return None
    host, registrable = parts.host, parts.registrable
    lowered = text.lower()
    if host in SHORT_LINK_DOMAINS or registrable in SHORT_LINK_DOMAINS:
        return ContactKind.SHORT_LINK, lowered, {"domain": registrable}
    if host in TELEGRAM_HOSTS:
        handle = lowered.split(host, 1)[1].strip("/").split("/")[0]
        return ContactKind.TELEGRAM, f"t.me/{handle}" if handle else host, {"domain": host}
    if host in WHATSAPP_HOSTS:
        digits = re.search(r"(\d{7,15})", text)
        phone = normalize_phone("+" + digits.group(1)) if digits else None
        return ContactKind.WHATSAPP, phone.e164 if phone else lowered, {"domain": host}
    if registrable in SOCIAL_DOMAINS:
        return ContactKind.SOCIAL_HANDLE, lowered, {"domain": registrable}
    kind = ContactKind.URL if "://" in text else ContactKind.DOMAIN
    detail = {"host": parts.host}
    if parts.is_idn:
        detail["idn"] = "true"
    return kind, registrable, detail


def _looks_like_run_on_sentence(candidate: str) -> bool:
    """'returns.Join' or 'Dubai.Office': a missing space, not a domain."""
    if candidate.lower().startswith("www.") or "/" in candidate:
        return False
    tld = candidate.rsplit(".", 1)[-1]
    return tld[:1].isupper() and tld[1:].islower()


def extract_contact_points(
    text: str, roles: Mapping[ContactKind, ContactRole] | None = None
) -> list[ContactPoint]:
    """Return every contact point in ``text``, ordered by position, with IDs ``cp1``, ``cp2`` …"""
    role_of = roles or DEFAULT_CONTACT_ROLES
    spans = _Spans()
    found: list[tuple[int, int, ContactKind, str, str, dict[str, str]]] = []

    def add(
        start: int, end: int, kind: ContactKind, normalized: str, detail: dict[str, str]
    ) -> None:
        found.append((start, end, kind, text[start:end], normalized, detail))

    for m in _URL.finditer(text):
        raw = m.group(0).rstrip(_TRAILING)
        start, end = m.start(), m.start() + len(raw)
        classified = _classify_link(raw)
        if classified and spans.take(start, end):
            add(start, end, *classified)

    for m in _EMAIL.finditer(text):
        if spans.take(m.start(), m.end()):
            email = m.group(0).lower()
            parts = domain_parts(email)
            add(
                m.start(),
                m.end(),
                ContactKind.EMAIL,
                email,
                {"domain": parts.registrable if parts else ""},
            )

    for m in _IBAN.finditer(text):
        if not spans.free(m.start(), m.end()):
            continue
        compact = m.group(0).replace(" ", "")
        try:
            IBAN(compact)
            valid = "true"
        except Exception:  # schwifty raises several validation error types
            valid = "false"
        spans.take(m.start(), m.end())
        add(m.start(), m.end(), ContactKind.IBAN, compact, {"valid": valid, "country": compact[:2]})

    for chain, pattern in _WALLETS:
        for m in pattern.finditer(text):
            if spans.take(m.start(), m.end()):
                add(m.start(), m.end(), ContactKind.WALLET, m.group(0), {"chain": chain})

    for scheme, pattern in _LICENCE_REFS:
        for m in pattern.finditer(text):
            group = 1 if pattern.groups else 0
            start, end = m.start(group), m.end(group)
            if spans.take(start, end):
                add(start, end, ContactKind.LICENCE_REF, m.group(group).upper(), {"scheme": scheme})

    for m in _DOMAIN.finditer(text):
        raw = m.group(0).rstrip(_TRAILING)
        start, end = m.start(), m.start() + len(raw)
        if _looks_like_run_on_sentence(raw) or not spans.free(start, end):
            continue
        classified = _classify_link(raw)
        if classified and spans.take(start, end):
            add(start, end, *classified)

    for match in phonenumbers.PhoneNumberMatcher(
        text, "AE", leniency=phonenumbers.Leniency.POSSIBLE
    ):
        raw = match.raw_string
        if not raw.lstrip("(").startswith(("+", "00", "0")):
            continue
        if len(re.sub(r"\D", "", raw)) < 8 or not spans.free(match.start, match.end):
            continue
        info = normalize_phone(raw)
        if info is None:
            continue
        spans.take(match.start, match.end)
        context = text[max(0, match.start - 40) : match.start].lower()
        kind = ContactKind.WHATSAPP if "whatsapp" in context else ContactKind.PHONE
        add(match.start, match.end, kind, info.e164, {"country_code": str(info.country_code)})

    for m in _HANDLE.finditer(text):
        if not spans.take(m.start(), m.end()):
            continue
        context = text[max(0, m.start() - 25) : m.start()].lower()
        kind = ContactKind.TELEGRAM if "telegram" in context else ContactKind.SOCIAL_HANDLE
        add(m.start(), m.end(), kind, m.group(0).lower(), {})

    addresses = [(m.start(1), m.end(1)) for m in _ADDRESS_LABEL.finditer(text)]
    if not addresses:
        lowered = text.casefold()
        for cue in _BUILDING_CUES:
            index = lowered.find(cue)
            if index >= 0:
                addresses.append((index, index + len(cue)))
    for start, end in addresses:
        fragment = text[start:end].strip()
        start = text.index(fragment, start)
        add(
            start,
            start + len(fragment),
            ContactKind.ADDRESS,
            fragment,
            {"zone": detect_zone(fragment)},
        )

    found.sort(key=lambda item: (item[0], item[1]))
    return [
        ContactPoint(
            cp_id=f"cp{index}",
            kind=kind,
            raw=raw,
            normalized=normalized,
            start=start,
            end=end,
            role=role_of[kind],
            detail=detail,
        )
        for index, (start, end, kind, raw, normalized, detail) in enumerate(found, start=1)
    ]

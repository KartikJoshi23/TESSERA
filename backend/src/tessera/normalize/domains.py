"""Domain normalisation: hosts, registrable domains and internationalised (IDN) names.

Uses the Public Suffix List snapshot bundled with ``tldextract`` and never fetches updates, so it
works offline. Reserved test TLDs (``.example``, ``.test``) used by fictional fixtures are
supported explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import tldextract

RESERVED_TLDS = frozenset({"example", "test", "invalid", "localhost"})

# Bundled snapshot only: suffix_list_urls=() disables network fetches; cache_dir=None disables
# writing a cache to disk.
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

_STRIP_CHARS = ".,;:!?)(\"'<>[]{}"


@dataclass(frozen=True)
class DomainParts:
    host: str  # ASCII (punycode) host, lower-case
    host_unicode: str  # Unicode form, for look-alike analysis
    subdomain: str
    sld: str  # registrable label, ASCII
    sld_unicode: str
    suffix: str
    registrable: str  # "sld.suffix", ASCII
    is_idn: bool


def _to_ascii(host: str) -> str:
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def _to_unicode(host: str) -> str:
    try:
        return host.encode("ascii").decode("idna")
    except UnicodeError:
        return host


def host_from(value: str) -> str | None:
    """Extract the host from a URL, bare domain or email address."""
    text = value.strip().strip(_STRIP_CHARS)
    if not text:
        return None
    if "://" not in text:
        if "@" in text:
            text = text.rsplit("@", 1)[1]
        text = "http://" + text
    try:
        host = urlsplit(text).hostname
    except ValueError:
        return None
    if not host or "." not in host:
        return None
    return host.rstrip(".").lower()


def domain_parts(value: str) -> DomainParts | None:
    """Split a URL, domain or email into its parts, or return ``None`` if it is not a domain."""
    host = host_from(value)
    if host is None:
        return None
    ascii_host = _to_ascii(host)
    extracted = _EXTRACT(ascii_host)
    if extracted.domain and extracted.suffix:
        sld, suffix, subdomain = extracted.domain, extracted.suffix, extracted.subdomain
    else:
        labels = ascii_host.split(".")
        if len(labels) >= 2 and labels[-1] in RESERVED_TLDS and labels[-2]:
            sld, suffix, subdomain = labels[-2], labels[-1], ".".join(labels[:-2])
        else:
            return None
    return DomainParts(
        host=ascii_host,
        host_unicode=_to_unicode(ascii_host),
        subdomain=subdomain,
        sld=sld,
        sld_unicode=_to_unicode(sld),
        suffix=suffix,
        registrable=f"{sld}.{suffix}",
        is_idn="xn--" in ascii_host,
    )


def registrable_domain(value: str | None) -> str | None:
    """``"https://www.Example.co.uk/x"`` → ``"example.co.uk"``; ``None`` if not a domain."""
    if not value:
        return None
    parts = domain_parts(value)
    return parts.registrable if parts else None

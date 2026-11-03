"""Evidence links that respect each source's linking rules.

The DFSA's terms allow links to its homepage only, so restricted sources (and any source without
deep-link permission) always resolve to the homepage. Other sources keep a deep link only if it
points at the source's own site.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from tessera.governance.network import host_matches
from tessera.governance.policies import SourcesPolicy

DFSA_HOMEPAGE = "https://www.dfsa.ae/"

#: "dfsa.ae/" followed by a path character. The bare homepage is allowed.
DFSA_DEEP_LINK = re.compile(r"dfsa\.ae/[A-Za-z0-9_\-%#?=&~][^\s)\"'<>\]`]*", re.IGNORECASE)


def find_dfsa_deep_links(text: str) -> list[str]:
    """Return every DFSA deep link in ``text`` (anything beyond the homepage)."""
    return [match.group(0) for match in DFSA_DEEP_LINK.finditer(text)]


def _site(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def sanitize_link(source_id: str, url: str | None, policy: SourcesPolicy) -> str:
    """Return a link for evidence from ``source_id`` that complies with its policy."""
    source = policy.source(source_id)
    if source.restricted or not source.deep_links_allowed:
        return source.homepage
    fallback = source.page_url or source.homepage
    candidate = url or fallback
    parts = urlsplit(candidate)
    home_host = urlsplit(source.homepage).hostname or ""
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return fallback
    if not host_matches(parts.hostname, [_site(home_host)]):
        return fallback
    return candidate

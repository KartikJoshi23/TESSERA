"""Look-alike analysis between an offer's domain and an official domain (deterministic).

The analysis detects these patterns:

* top-level-domain swaps;
* character look-alikes, including punycode;
* added words ("combosquatting");
* truncations and abbreviations;
* small edit distances.

A look-alike of an official domain is hard conflict HC5. A different domain that does not look
alike is only "not on record" (reason U3). Thresholds come from ``policies/decision_policy.yaml``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein

from tessera.normalize.domains import domain_parts
from tessera.protocol.evidence import EvidenceKind, EvidenceRecord, ToolResult, mint_evidence
from tessera.tools.context import ToolContext

# Characters that imitate Latin letters, mapped to one representative each. i-like and l-like
# characters all collapse to "l".
_CONFUSABLES = str.maketrans(
    {
        "0": "o",
        "1": "l",
        "3": "e",
        "5": "s",
        "|": "l",
        "!": "l",
        "i": "l",
        "ı": "l",
        "і": "l",
        "ӏ": "l",
        "ι": "l",
        "ǀ": "l",
        "а": "a",
        "α": "a",
        "е": "e",
        "ε": "e",
        "о": "o",
        "ο": "o",
        "σ": "o",
        "р": "p",
        "ρ": "p",
        "с": "c",
        "ϲ": "c",
        "у": "y",
        "γ": "y",
        "х": "x",
        "χ": "x",
        "к": "k",
        "κ": "k",
        "м": "m",
        "т": "t",
        "τ": "t",
        "ѕ": "s",
        "ј": "j",
        "һ": "h",
        "ԁ": "d",
        "ԛ": "q",
        "ԝ": "w",
        "ν": "v",
        "υ": "u",
        "ɡ": "g",
        "п": "n",
        "г": "r",
        "ь": "b",
    }
)
_MULTI_CHAR = (("rn", "m"), ("vv", "w"))
_TRUNCATION_MIN_RATIO = 0.6


def skeleton(label: str) -> str:
    """A visual skeleton: two labels that look alike share the same skeleton."""
    text = unicodedata.normalize("NFKD", label.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).translate(_CONFUSABLES)
    for pair, replacement in _MULTI_CHAR:
        text = text.replace(pair, replacement)
    return text.replace("-", "").replace("_", "")


def _is_subsequence(short: str, long: str) -> bool:
    remaining = iter(long)
    return all(char in remaining for char in short)


@dataclass(frozen=True)
class DomainComparison:
    offer_registrable: str | None
    official_registrable: str | None
    same_registrable: bool
    tld_swap: bool
    edit_distance: int | None
    similarity: float | None
    skeleton_equal: bool
    brand_contained: bool
    added_tokens: tuple[str, ...]
    truncation: bool
    offer_is_idn: bool
    lookalike: bool
    patterns: tuple[str, ...]


def compare_domains(
    offer: str,
    official: str,
    *,
    max_edit_distance: int,
    min_similarity: float,
    min_brand_length: int,
) -> DomainComparison:
    """Compare two domains (URLs and emails are accepted) and classify the relationship."""
    a, b = domain_parts(offer), domain_parts(official)
    if a is None or b is None:
        return DomainComparison(
            offer_registrable=a.registrable if a else None,
            official_registrable=b.registrable if b else None,
            same_registrable=False,
            tld_swap=False,
            edit_distance=None,
            similarity=None,
            skeleton_equal=False,
            brand_contained=False,
            added_tokens=(),
            truncation=False,
            offer_is_idn=bool(a and a.is_idn),
            lookalike=False,
            patterns=("not_comparable",),
        )
    same = a.registrable == b.registrable
    sa, sb = a.sld_unicode.casefold(), b.sld_unicode.casefold()
    flat_a, flat_b = sa.replace("-", ""), sb.replace("-", "")
    tld_swap = not same and a.sld == b.sld
    distance = DamerauLevenshtein.distance(sa, sb)
    similarity = round(fuzz.ratio(sa, sb) / 100, 3)
    homoglyph = not same and sa != sb and skeleton(sa) == skeleton(sb)
    contained = (
        not same and len(flat_b) >= min_brand_length and flat_b in flat_a and flat_a != flat_b
    )
    added: tuple[str, ...] = ()
    if contained:
        pieces = [p for p in re.split(r"[-_]", sa) if p]
        added = (
            tuple(p for p in pieces if p != flat_b)
            if len(pieces) > 1
            else tuple(p for p in flat_a.split(flat_b) if p)
        )
    long_enough = min(len(flat_a), len(flat_b)) >= min_brand_length
    truncation = (
        not same
        and long_enough
        and len(flat_a) < len(flat_b)
        and len(flat_a) / len(flat_b) >= _TRUNCATION_MIN_RATIO
        and flat_a[:3] == flat_b[:3]
        and _is_subsequence(flat_a, flat_b)
    )
    near = (
        not same and long_enough and (distance <= max_edit_distance or similarity >= min_similarity)
    )

    patterns: list[str] = []
    if same:
        patterns.append("same_registrable_domain")
    if tld_swap:
        patterns.append("tld_swap")
    if homoglyph:
        patterns.append("homoglyph")
    if contained:
        patterns.append("added_word")
    if truncation:
        patterns.append("truncation_or_abbreviation")
    if near and not (tld_swap or homoglyph):
        patterns.append(
            f"edit_distance_{distance}" if distance <= max_edit_distance else "high_similarity"
        )
    if a.is_idn:
        patterns.append("idn")

    return DomainComparison(
        offer_registrable=a.registrable,
        official_registrable=b.registrable,
        same_registrable=same,
        tld_swap=tld_swap,
        edit_distance=distance,
        similarity=similarity,
        skeleton_equal=homoglyph,
        brand_contained=contained,
        added_tokens=added,
        truncation=truncation,
        offer_is_idn=a.is_idn,
        lookalike=not same and (tld_swap or homoglyph or contained or truncation or near),
        patterns=tuple(patterns),
    )


def compare_domain(
    ctx: ToolContext,
    offer_domain: str,
    official_domain: str,
    official_evidence: EvidenceRecord | None = None,
) -> ToolResult:
    """Tool wrapper: compare and mint a derived-analysis evidence record."""
    t = ctx.decision.thresholds
    result = compare_domains(
        offer_domain,
        official_domain,
        max_edit_distance=t.lookalike_max_edit_distance,
        min_similarity=t.lookalike_min_similarity,
        min_brand_length=t.lookalike_min_brand_length,
    )
    restricted = bool(official_evidence and official_evidence.restricted)
    fields: dict[str, object] = {
        "lookalike": result.lookalike,
        "same_registrable": result.same_registrable,
        "edit_distance": result.edit_distance,
        "patterns": list(result.patterns),
    }
    if not restricted:
        fields |= {
            "offer_domain": result.offer_registrable,
            "official_domain": result.official_registrable,
            "added_tokens": list(result.added_tokens),
            "similarity": result.similarity,
        }
    offer_key = hashlib.sha256((result.offer_registrable or offer_domain).encode()).hexdigest()[:8]
    official_key = official_evidence.evidence_id if official_evidence else "unlinked"
    evidence = mint_evidence(
        case_id=ctx.case_id,
        source_id="derived",
        kind=EvidenceKind.DERIVED_ANALYSIS,
        locator=f"compare_domain:{offer_key}:{official_key}",
        fields=fields,
        minted_by="compare_domain",
        restricted=restricted,
        restricted_ref=official_evidence.restricted_ref
        if restricted and official_evidence
        else None,
    )
    summary = {
        "evidence_id": evidence.evidence_id,
        "official_evidence_id": official_evidence.evidence_id if official_evidence else None,
        "offer_domain": result.offer_registrable,
        "official_domain": result.official_registrable,
        "lookalike": result.lookalike,
        "same_registrable": result.same_registrable,
        "patterns": list(result.patterns),
        "added_tokens": list(result.added_tokens),
        "edit_distance": result.edit_distance,
    }
    return ToolResult(
        tool="compare_domain", evidence=(evidence,), summary=summary, restricted=restricted
    )

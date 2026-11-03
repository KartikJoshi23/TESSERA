"""Compare an offer's phone number with the official numbers on record (E.164 equality).

A number's validity, country or type is reported as context only. It is never a signal on its
own, because synthetic offers use ranges reserved for fiction.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from tessera.normalize.phones import normalize_phone
from tessera.protocol.evidence import EvidenceKind, EvidenceRecord, ToolResult, mint_evidence
from tessera.tools.context import ToolContext


def analyse_phone(
    ctx: ToolContext,
    offer_phone: str,
    official_phones: Sequence[str],
    official_evidence: EvidenceRecord | None = None,
) -> ToolResult:
    offer = normalize_phone(offer_phone)
    officials = [info for info in (normalize_phone(p) for p in official_phones) if info]
    equal = offer is not None and any(o.e164 == offer.e164 for o in officials)
    restricted = bool(official_evidence and official_evidence.restricted)
    fields: dict[str, object] = {"equal_to_official": equal, "matched_on": "phone"}
    if not restricted:
        fields |= {
            "offer_e164": offer.e164 if offer else None,
            "official_count": len(officials),
        }
    offer_key = hashlib.sha256((offer.e164 if offer else offer_phone).encode()).hexdigest()[:8]
    official_key = official_evidence.evidence_id if official_evidence else "unlinked"
    evidence = mint_evidence(
        case_id=ctx.case_id,
        source_id="derived",
        kind=EvidenceKind.DERIVED_ANALYSIS,
        locator=f"analyse_phone:{offer_key}:{official_key}",
        fields=fields,
        minted_by="analyse_phone",
        restricted=restricted,
        restricted_ref=official_evidence.restricted_ref
        if restricted and official_evidence
        else None,
    )
    summary = {
        "evidence_id": evidence.evidence_id,
        "offer_e164": offer.e164 if offer else None,
        "offer_country_code": offer.country_code if offer else None,
        "offer_region": offer.region if offer else None,
        "offer_type": offer.number_type if offer else None,
        "equal_to_official": equal,
        "comparable": offer is not None and bool(officials),
    }
    return ToolResult(
        tool="analyse_phone", evidence=(evidence,), summary=summary, restricted=restricted
    )

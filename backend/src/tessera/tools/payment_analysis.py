"""Payment details against the claimed firm's record (hard conflict HC6 and scope signals).

The analysis covers three things:

* an IBAN's checksum and country;
* whether the payment beneficiary matches the registered legal name;
* whether the offer asks for crypto payment.

Whether crypto is within the firm's licence is decided later from the licence-scope finding.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from schwifty import IBAN

from tessera.protocol.evidence import EvidenceKind, EvidenceRecord, ToolResult, mint_evidence
from tessera.tools.context import ToolContext
from tessera.tools.matching import match_name

_WALLET_PREFIXES = (("0x", "ETH"), ("bc1", "BTC"), ("T", "TRON"), ("1", "BTC"), ("3", "BTC"))


def _iban_facts(iban: str | None) -> tuple[bool | None, str | None]:
    if not iban:
        return None, None
    compact = "".join(iban.split()).upper()
    try:
        IBAN(compact)
    except Exception:  # schwifty raises several validation error types
        return False, compact[:2] or None
    return True, compact[:2]


def _wallet_chain(wallet: str | None) -> str | None:
    if not wallet:
        return None
    return next(
        (chain for prefix, chain in _WALLET_PREFIXES if wallet.startswith(prefix)), "UNKNOWN"
    )


def analyse_payment(
    ctx: ToolContext,
    *,
    iban: str | None = None,
    beneficiary: str | None = None,
    wallet: str | None = None,
    entity_names: Sequence[str] = (),
    entity_evidence: EvidenceRecord | None = None,
) -> ToolResult:
    t = ctx.decision.thresholds
    iban_valid, iban_country = _iban_facts(iban)
    beneficiary_matches: bool | None = None
    match_type = "none"
    if beneficiary and entity_names:
        matches = match_name(
            beneficiary,
            [("entity", list(entity_names))],
            tau1=t.name_fuzzy_tau1,
            tau2=t.name_partial_tau2,
            partial_min_length=t.partial_min_length,
        )
        beneficiary_matches = bool(matches) and matches[0].match_type in {"exact", "alias", "fuzzy"}
        match_type = matches[0].match_type if matches else "none"
    fields: dict[str, object] = {
        "iban_valid": iban_valid,
        "iban_country": iban_country,
        "beneficiary_matches": beneficiary_matches,
        "match_type": match_type,
        "wallet_requested": bool(wallet),
        "wallet_chain": _wallet_chain(wallet),
    }
    restricted = bool(entity_evidence and entity_evidence.restricted)
    material = "|".join(str(x) for x in (iban, beneficiary, wallet))
    entity_key = entity_evidence.evidence_id if entity_evidence else "unlinked"
    evidence = mint_evidence(
        case_id=ctx.case_id,
        source_id="derived",
        kind=EvidenceKind.DERIVED_ANALYSIS,
        locator=f"analyse_payment:{hashlib.sha256(material.encode()).hexdigest()[:8]}:{entity_key}",
        fields=fields,
        minted_by="analyse_payment",
        restricted=restricted,
        restricted_ref=entity_evidence.restricted_ref if restricted and entity_evidence else None,
    )
    return ToolResult(
        tool="analyse_payment",
        evidence=(evidence,),
        summary={"evidence_id": evidence.evidence_id, **fields},
        restricted=restricted,
    )

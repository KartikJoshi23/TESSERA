"""Deterministic register and list lookups.

Every lookup creates evidence: one record per match, or an explicit no-match record, so that a
statement such as "not found on the VARA register as of 5 Nov 2026" is as checkable as a match.
If a source has no snapshot yet, the lookup creates no evidence and says so (reason U7), because
an empty table proves nothing.

DFSA lookups run only in ``RESEARCH_INTERNAL`` mode. Their evidence holds row references and
derived fields only; identifying values appear only in the summary, which is flagged
``restricted`` and must be masked before any model call.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from tessera.data.registry import FactTable
from tessera.data.schemas import (
    BaseRecord,
    CmaLicensedRecord,
    DfsaAlertFact,
    DfsaRegisterFact,
    VaraRegisterRecord,
)
from tessera.governance.links import DFSA_HOMEPAGE
from tessera.governance.masking import classify_value
from tessera.normalize.domains import registrable_domain
from tessera.normalize.phones import normalize_phone
from tessera.protocol.evidence import EvidenceKind, EvidenceRecord, ToolResult, mint_evidence
from tessera.tools.context import ToolContext
from tessera.tools.matching import MATCH_RANK, match_name

DFSA_UNAVAILABLE_MESSAGE = (
    "DFSA facts are not loaded in this mode. Manual check required at https://www.dfsa.ae/"
)


R = TypeVar("R", bound=BaseRecord)


def _typed(table: FactTable, model: type[R]) -> list[R]:
    """Records of ``table`` as their concrete schema (each table holds one source's model)."""
    return [cast(R, record) for record in table.records]


@dataclass(frozen=True)
class _Hit:
    record: Any  # a BaseRecord subclass
    match_type: str
    matched_on: str
    score: float


# --------------------------------------------------------------------------- normalisers


def _norm_ref(value: str | None) -> str | None:
    return "".join(value.split()).upper() if value else None


def _e164(value: str | None) -> str | None:
    info = normalize_phone(value) if value else None
    return info.e164 if info else None


def _email(value: str | None) -> str | None:
    return value.strip().lower() if value and "@" in value and not value.startswith("@") else None


def _clean(values: Iterable[str | None]) -> list[str]:
    return sorted({v for v in values if v})


# --------------------------------------------------------------------------- matching helpers


def _best(hits: Iterable[_Hit], limit: int) -> list[_Hit]:
    best: dict[str, _Hit] = {}
    for hit in hits:
        current = best.get(hit.record.record_id)
        if current is None or (MATCH_RANK[hit.match_type], -hit.score) < (
            MATCH_RANK[current.match_type],
            -current.score,
        ):
            best[hit.record.record_id] = hit
    ranked = sorted(
        best.values(), key=lambda h: (MATCH_RANK[h.match_type], -h.score, h.record.record_id)
    )
    return ranked[:limit]


def _name_hits(ctx: ToolContext, table: FactTable, name: str, label: str = "name") -> list[_Hit]:
    t = ctx.decision.thresholds
    by_id = {record.record_id: record for record in table.records}
    matches = match_name(
        name,
        [(record.record_id, record.names()) for record in table.records],
        tau1=t.name_fuzzy_tau1,
        tau2=t.name_partial_tau2,
        partial_min_length=t.partial_min_length,
        limit=10,
    )
    return [_Hit(by_id[m.record_id], m.match_type, label, m.score) for m in matches]


def _domain_hits(table: FactTable, domain: str) -> list[_Hit]:
    target = registrable_domain(domain)
    if not target:
        return []
    return [
        _Hit(r, "exact", "domain", 100.0)
        for r in table.records
        if target in {registrable_domain(d) for d in r.domains()}
    ]


def _phone_hits(table: FactTable, phone: str) -> list[_Hit]:
    target = _e164(phone)
    if not target:
        return []
    return [
        _Hit(r, "exact", "phone", 100.0)
        for r in table.records
        if target in {_e164(p) for p in r.phones()}
    ]


def _email_hits(table: FactTable, email: str) -> list[_Hit]:
    target = _email(email)
    if not target:
        return []
    domain = registrable_domain(target)
    hits: list[_Hit] = []
    for r in table.records:
        if target in {_email(e) for e in r.emails()}:
            hits.append(_Hit(r, "exact", "email", 100.0))
        elif domain and domain in {registrable_domain(d) for d in r.domains()}:
            hits.append(_Hit(r, "exact", "email_domain", 100.0))
    return hits


def _contact_in(
    values: Sequence[str],
    *,
    domain: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> bool:
    """True if any of ``domain``/``email``/``phone`` matches a contact recorded in ``values``."""
    domains = {
        registrable_domain(v.lstrip("@"))
        for v in values
        if classify_value(v) in ("domain", "email")
    }
    domains.discard(None)
    phones = {_e164(v) for v in values if classify_value(v) == "phone"}
    phones.discard(None)
    emails = {_email(v) for v in values}
    emails.discard(None)
    if domain and registrable_domain(domain) in domains:
        return True
    if email and (_email(email) in emails or registrable_domain(email) in domains):
        return True
    return bool(phone and _e164(phone) in phones)


# --------------------------------------------------------------------------- evidence helpers


def _snapshot(table: FactTable) -> dict[str, Any]:
    manifest = table.manifest
    return {
        "snapshot_id": manifest.snapshot_id if manifest else None,
        "snapshot_date": manifest.retrieved_on if manifest else None,
    }


def _unavailable(tool: str, source_id: str, **extra: Any) -> ToolResult:
    return ToolResult(
        tool=tool,
        summary={
            "source_id": source_id,
            "available": False,
            "reason": "no snapshot has been ingested for this source",
            **extra,
        },
        warnings=(f"{source_id}: no snapshot ingested",),
    )


def _no_match(
    ctx: ToolContext, table: FactTable, tool: str, query: dict[str, Any]
) -> EvidenceRecord:
    searched = sorted(key for key, value in query.items() if value)
    if table.restricted:
        return mint_evidence(
            case_id=ctx.case_id,
            source_id=table.source_id,
            kind=EvidenceKind.NO_MATCH,
            locator="no-match",
            fields={"record_kind": table.source_id, "searched": searched},
            minted_by=tool,
            restricted=True,
            restricted_ref=f"{table.source_id}:no-match",
            display_link=ctx.link(table.source_id),
            **_snapshot(table),
        )
    return mint_evidence(
        case_id=ctx.case_id,
        source_id=table.source_id,
        kind=EvidenceKind.NO_MATCH,
        locator="no-match",
        fields={"query": {k: v for k, v in query.items() if v}, "searched": searched},
        minted_by=tool,
        display_link=ctx.link(table.source_id),
        **_snapshot(table),
    )


def _restricted_evidence(
    ctx: ToolContext,
    table: FactTable,
    tool: str,
    kind: EvidenceKind,
    record: BaseRecord,
    *,
    match_type: str,
    matched_on: str,
    score: float,
    record_kind: str,
) -> EvidenceRecord:
    return mint_evidence(
        case_id=ctx.case_id,
        source_id=table.source_id,
        kind=kind,
        locator=record.record_id,
        fields={
            "record_kind": record_kind,
            "match_type": match_type,
            "matched_on": matched_on,
            "score": score,
        },
        minted_by=tool,
        restricted=True,
        restricted_ref=f"{table.source_id}:{record.record_id}",
        display_link=DFSA_HOMEPAGE,
        **_snapshot(table),
    )


def _lookup(
    ctx: ToolContext,
    *,
    tool: str,
    source_id: str,
    kind: EvidenceKind,
    hits_fn: Callable[[FactTable], list[_Hit]],
    fields_fn: Callable[[Any], dict[str, Any]],
    query: dict[str, Any],
    limit: int,
) -> ToolResult:
    table = ctx.registry.table(source_id)
    if not table.available:
        return _unavailable(tool, source_id)
    hits = _best(hits_fn(table), limit)
    evidence: list[EvidenceRecord] = []
    matches: list[dict[str, Any]] = []
    for hit in hits:
        fields = {
            **fields_fn(hit.record),
            "match_type": hit.match_type,
            "matched_on": hit.matched_on,
            "score": hit.score,
        }
        record = mint_evidence(
            case_id=ctx.case_id,
            source_id=source_id,
            kind=kind,
            locator=hit.record.record_id,
            fields=fields,
            minted_by=tool,
            display_link=ctx.link(source_id, getattr(hit.record, "page_url", None)),
            **_snapshot(table),
        )
        evidence.append(record)
        matches.append({"evidence_id": record.evidence_id, **fields})
    meta = _snapshot(table)
    summary: dict[str, Any] = {
        "source_id": source_id,
        "available": True,
        "snapshot_id": meta["snapshot_id"],
        "snapshot_date": str(meta["snapshot_date"]),
        "matches": matches,
    }
    if not hits:
        no_match = _no_match(ctx, table, tool, query)
        evidence.append(no_match)
        summary["no_match_evidence_id"] = no_match.evidence_id
    return ToolResult(tool=tool, evidence=tuple(evidence), summary=summary)


# --------------------------------------------------------------------------- record payloads


def _cma_fields(r: Any) -> dict[str, Any]:
    return {
        "record_id": r.record_id,
        "name_en": r.name_en,
        "name_ar": r.name_ar,
        "licence_no": r.licence_no,
        "category": r.category,
        "activities": list(r.activities),
        "status": r.status,
        "emirate": r.emirate,
        "website_domain": registrable_domain(r.website),
        "phone": _e164(r.phone),
        "email": _email(r.email),
    }


def _warning_fields(r: Any) -> dict[str, Any]:
    return {
        "record_id": r.record_id,
        "entity_name": r.entity_name,
        "warning_date": r.warning_date.isoformat() if r.warning_date else None,
        "domains": _clean(registrable_domain(d) for d in r.domains()),
        "phones": _clean(_e164(p) for p in r.phones()),
        "emails": _clean(_email(e) for e in r.emails()),
    }


def _vara_fields(r: Any) -> dict[str, Any]:
    return {
        "record_id": r.record_id,
        "entity_name": r.entity_name,
        "status": r.status,
        "licence_ref": r.licence_ref,
        "activities": list(r.activities),
        "website_domain": registrable_domain(r.website),
    }


def _unlicensed_fields(r: Any) -> dict[str, Any]:
    return {
        "record_id": r.record_id,
        "entity_name": r.entity_name,
        "domains": _clean(registrable_domain(d) for d in r.domains()),
        "date_listed": r.date_listed.isoformat() if r.date_listed else None,
    }


# --------------------------------------------------------------------------- public tools


def cma_register_lookup(
    ctx: ToolContext,
    *,
    name: str | None = None,
    licence_no: str | None = None,
    domain: str | None = None,
    limit: int = 3,
) -> ToolResult:
    """Search the CMA Licensed Companies snapshot by name, licence number or website."""

    def hits(table: FactTable) -> list[_Hit]:
        found: list[_Hit] = []
        if licence_no:
            ref = _norm_ref(licence_no)
            found += [
                _Hit(r, "reference", "licence_no", 100.0)
                for r in _typed(table, CmaLicensedRecord)
                if _norm_ref(r.licence_no) == ref
            ]
        if domain:
            found += _domain_hits(table, domain)
        if name:
            found += _name_hits(ctx, table, name)
        return found

    return _lookup(
        ctx,
        tool="cma_register_lookup",
        source_id="cma_licensed",
        kind=EvidenceKind.REGISTER_ENTRY,
        hits_fn=hits,
        fields_fn=_cma_fields,
        query={"name": name, "licence_no": licence_no, "domain": domain},
        limit=limit,
    )


def cma_warnings_lookup(
    ctx: ToolContext,
    *,
    name: str | None = None,
    domain: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    limit: int = 5,
) -> ToolResult:
    """Search the CMA Warnings snapshot."""

    def hits(table: FactTable) -> list[_Hit]:
        found: list[_Hit] = []
        if name:
            found += _name_hits(ctx, table, name)
        if domain:
            found += _domain_hits(table, domain)
        if phone:
            found += _phone_hits(table, phone)
        if email:
            found += _email_hits(table, email)
        return found

    return _lookup(
        ctx,
        tool="cma_warnings_lookup",
        source_id="cma_warnings",
        kind=EvidenceKind.WARNING_ENTRY,
        hits_fn=hits,
        fields_fn=_warning_fields,
        query={"name": name, "domain": domain, "phone": phone, "email": email},
        limit=limit,
    )


def vara_register_lookup(
    ctx: ToolContext,
    *,
    name: str | None = None,
    licence_ref: str | None = None,
    domain: str | None = None,
    limit: int = 3,
) -> ToolResult:
    """Search the VARA Public Register snapshot. Licensed VASPs and IPA holders stay separate."""

    def hits(table: FactTable) -> list[_Hit]:
        found: list[_Hit] = []
        if licence_ref:
            ref = _norm_ref(licence_ref)
            found += [
                _Hit(r, "reference", "licence_ref", 100.0)
                for r in _typed(table, VaraRegisterRecord)
                if _norm_ref(r.licence_ref) == ref
            ]
        if domain:
            found += _domain_hits(table, domain)
        if name:
            found += _name_hits(ctx, table, name)
        return found

    result = _lookup(
        ctx,
        tool="vara_register_lookup",
        source_id="vara_register",
        kind=EvidenceKind.REGISTER_ENTRY,
        hits_fn=hits,
        fields_fn=_vara_fields,
        query={"name": name, "licence_ref": licence_ref, "domain": domain},
        limit=limit,
    )
    if not result.summary.get("available"):
        return result
    matches = result.summary["matches"]
    summary = {
        **result.summary,
        "licensed": [m["evidence_id"] for m in matches if m["status"] == "LICENSED"],
        "in_principle_approval": [m["evidence_id"] for m in matches if m["status"] == "IPA"],
    }
    return result.model_copy(update={"summary": summary})


def vara_unlicensed_lookup(
    ctx: ToolContext, *, name: str | None = None, domain: str | None = None, limit: int = 5
) -> ToolResult:
    """Search VARA's Unlicensed VASPs snapshot."""

    def hits(table: FactTable) -> list[_Hit]:
        found: list[_Hit] = []
        if name:
            found += _name_hits(ctx, table, name)
        if domain:
            found += _domain_hits(table, domain)
        return found

    return _lookup(
        ctx,
        tool="vara_unlicensed_lookup",
        source_id="vara_unlicensed",
        kind=EvidenceKind.UNLICENSED_ENTRY,
        hits_fn=hits,
        fields_fn=_unlicensed_fields,
        query={"name": name, "domain": domain},
        limit=limit,
    )


def dfsa_facts_lookup(
    ctx: ToolContext,
    *,
    name: str | None = None,
    frn: str | None = None,
    domain: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    limit: int = 3,
) -> ToolResult:
    """Search the hand-recorded DFSA register and alert facts (research mode only)."""
    tool = "dfsa_facts_lookup"
    if not ctx.registry.restricted_allowed:
        return ToolResult(
            tool=tool,
            summary={
                "source_id": "dfsa",
                "available": False,
                "reason": "restricted",
                "message": DFSA_UNAVAILABLE_MESSAGE,
                "link": DFSA_HOMEPAGE,
            },
            warnings=("DFSA facts are unavailable in RESTRICTED_DEMO mode",),
        )
    register = ctx.registry.table("dfsa_register")
    alerts = ctx.registry.table("dfsa_alerts")
    if not (register.available or alerts.available):
        return _unavailable(tool, "dfsa", link=DFSA_HOMEPAGE)

    query = {"name": name, "frn": frn, "domain": domain, "email": email, "phone": phone}
    evidence: list[EvidenceRecord] = []
    register_matches: list[dict[str, Any]] = []
    alert_matches: list[dict[str, Any]] = []

    if register.available:
        found: list[_Hit] = []
        if frn:
            found += [
                _Hit(r, "reference", "frn", 100.0)
                for r in _typed(register, DfsaRegisterFact)
                if _norm_ref(r.frn) == _norm_ref(frn)
            ]
        if name:
            found += _name_hits(ctx, register, name)
        if domain:
            found += _domain_hits(register, domain)
        if email:
            found += _email_hits(register, email)
        if phone:
            found += _phone_hits(register, phone)
        best = _best(found, limit)
        for hit in best:
            r = hit.record
            ev = _restricted_evidence(
                ctx,
                register,
                tool,
                EvidenceKind.REGISTER_ENTRY,
                r,
                match_type=hit.match_type,
                matched_on=hit.matched_on,
                score=hit.score,
                record_kind="register",
            )
            evidence.append(ev)
            register_matches.append(
                {
                    "evidence_id": ev.evidence_id,
                    "record_ref": ev.restricted_ref,
                    "firm_name": r.firm_name,
                    "frn": r.frn,
                    "status": r.status,
                    "permitted_services": list(r.permitted_services),
                    "address": r.address,
                    "website_domain": registrable_domain(r.website),
                    "phone": _e164(r.phone),
                    "email_domains": _clean(registrable_domain(d) for d in r.email_domains),
                    "match_type": hit.match_type,
                    "matched_on": hit.matched_on,
                    "score": hit.score,
                }
            )
        if not best:
            evidence.append(_no_match(ctx, register, tool, query))

    if alerts.available:
        labels: dict[str, set[str]] = {}
        records: dict[str, Any] = {}
        for r in _typed(alerts, DfsaAlertFact):
            matched: set[str] = set()
            if frn and _norm_ref(r.frn_named) == _norm_ref(frn):
                matched.add("frn_named")
            if _contact_in(r.contact_points_named, domain=domain, email=email, phone=phone):
                matched.add("contact_named")
            if _contact_in(r.legitimate_contacts_stated, domain=domain, email=email, phone=phone):
                matched.add("contact_legitimate")
            if matched:
                labels[r.record_id], records[r.record_id] = matched, r
        if name:
            for hit in _name_hits(ctx, alerts, name, label="firm_named"):
                labels.setdefault(hit.record.record_id, set()).add("firm_named")
                records[hit.record.record_id] = hit.record
        for record_id in sorted(labels):
            r = records[record_id]
            matched_on = ",".join(sorted(labels[record_id]))
            ev = _restricted_evidence(
                ctx,
                alerts,
                tool,
                EvidenceKind.ALERT_ENTRY,
                r,
                match_type="exact",
                matched_on=matched_on,
                score=100.0,
                record_kind="alert",
            )
            evidence.append(ev)
            alert_matches.append(
                {
                    "evidence_id": ev.evidence_id,
                    "record_ref": ev.restricted_ref,
                    "alert_date": r.alert_date.isoformat(),
                    "category": r.category,
                    "firm_named": r.firm_named,
                    "frn_named": r.frn_named,
                    "named_contacts": list(r.contact_points_named),
                    "legitimate_contacts": list(r.legitimate_contacts_stated),
                    "matched_on": matched_on,
                }
            )
        if not labels:
            evidence.append(_no_match(ctx, alerts, tool, query))

    summary = {
        "source_id": "dfsa",
        "available": True,
        "link": DFSA_HOMEPAGE,
        "register_available": register.available,
        "alerts_available": alerts.available,
        "register_matches": register_matches,
        "alert_matches": alert_matches,
    }
    return ToolResult(tool=tool, evidence=tuple(evidence), summary=summary, restricted=True)


def reverse_contact_lookup(ctx: ToolContext, value: str) -> ToolResult:
    """Search every alert, warning and unlicensed list for one domain, email or phone."""
    tool = "reverse_contact_lookup"
    kind = classify_value(value)
    if kind not in ("domain", "email", "phone"):
        return ToolResult(
            tool=tool,
            summary={"value_kind": kind, "comparable": False, "hits": [], "checked": []},
            warnings=("the value is not a domain, email or phone number",),
        )
    query = {
        "domain": value if kind == "domain" else None,
        "email": value if kind == "email" else None,
        "phone": value if kind == "phone" else None,
    }
    evidence: list[EvidenceRecord] = []
    hits: list[dict[str, Any]] = []
    checked: list[str] = []
    unavailable: list[str] = []

    public_lists = (
        ("cma_warnings", EvidenceKind.WARNING_ENTRY, _warning_fields),
        ("vara_unlicensed", EvidenceKind.UNLICENSED_ENTRY, _unlicensed_fields),
    )
    for source_id, evidence_kind, fields_fn in public_lists:
        table = ctx.registry.table(source_id)
        if not table.available:
            unavailable.append(source_id)
            continue
        checked.append(source_id)
        found: list[_Hit] = []
        if query["domain"]:
            found += _domain_hits(table, query["domain"])
        if query["email"]:
            found += _email_hits(table, query["email"])
        if query["phone"]:
            found += _phone_hits(table, query["phone"])
        best = _best(found, 10)
        for hit in best:
            fields = {
                **fields_fn(hit.record),
                "match_type": hit.match_type,
                "matched_on": hit.matched_on,
            }
            ev = mint_evidence(
                case_id=ctx.case_id,
                source_id=source_id,
                kind=evidence_kind,
                locator=hit.record.record_id,
                fields=fields,
                minted_by=tool,
                display_link=ctx.link(source_id, getattr(hit.record, "page_url", None)),
                **_snapshot(table),
            )
            evidence.append(ev)
            hits.append({"source_id": source_id, "evidence_id": ev.evidence_id, **fields})
        if not best:
            evidence.append(_no_match(ctx, table, tool, query))

    restricted = False
    if ctx.registry.restricted_allowed:
        alerts = ctx.registry.table("dfsa_alerts")
        if alerts.available:
            checked.append("dfsa_alerts")
            matched_any = False
            for r in _typed(alerts, DfsaAlertFact):
                for values, label in (
                    (r.contact_points_named, "contact_named"),
                    (r.legitimate_contacts_stated, "contact_legitimate"),
                ):
                    if not _contact_in(values, **query):
                        continue
                    matched_any = restricted = True
                    ev = _restricted_evidence(
                        ctx,
                        alerts,
                        tool,
                        EvidenceKind.ALERT_ENTRY,
                        r,
                        match_type="exact",
                        matched_on=label,
                        score=100.0,
                        record_kind="alert",
                    )
                    evidence.append(ev)
                    hits.append(
                        {
                            "source_id": "dfsa_alerts",
                            "evidence_id": ev.evidence_id,
                            "record_ref": ev.restricted_ref,
                            "alert_date": r.alert_date.isoformat(),
                            "category": r.category,
                            "firm_named": r.firm_named,
                            "matched_on": label,
                        }
                    )
            if not matched_any:
                evidence.append(_no_match(ctx, alerts, tool, query))
        else:
            unavailable.append("dfsa_alerts")
    else:
        unavailable.append("dfsa_alerts (restricted; not loaded in this mode)")

    summary = {
        "value_kind": kind,
        "comparable": True,
        "hits": hits,
        "checked": checked,
        "unavailable": unavailable,
    }
    return ToolResult(tool=tool, evidence=tuple(evidence), summary=summary, restricted=restricted)


def official_contacts_for(ctx: ToolContext, evidence: EvidenceRecord) -> ToolResult:
    """Official contact points recorded on a register entry. Cites that entry; mints nothing."""
    tool = "official_contacts_for"
    if evidence.kind is not EvidenceKind.REGISTER_ENTRY:
        raise ValueError("official contacts come from register entries only")
    if evidence.case_id != ctx.case_id:
        raise ValueError("the evidence belongs to another case")
    if evidence.source_id == "dfsa_register" and not ctx.registry.restricted_allowed:
        return ToolResult(
            tool=tool, summary={"available": False, "message": DFSA_UNAVAILABLE_MESSAGE}
        )
    record = ctx.registry.table(evidence.source_id).get(evidence.locator)
    if record is None:
        return ToolResult(
            tool=tool,
            summary={"available": False, "message": "the cited record is not in the snapshot"},
            warnings=("cited record not found",),
        )
    email_domains = [registrable_domain(e) for e in record.emails()]
    if evidence.source_id == "dfsa_register":
        dfsa_record = cast(DfsaRegisterFact, record)
        email_domains += [registrable_domain(d) for d in dfsa_record.email_domains]
    summary = {
        "available": True,
        "evidence_id": evidence.evidence_id,
        "source_id": evidence.source_id,
        "domains": _clean(registrable_domain(d) for d in record.domains()),
        "phones": _clean(_e164(p) for p in record.phones()),
        "email_domains": _clean(email_domains),
    }
    return ToolResult(tool=tool, summary=summary, restricted=evidence.restricted)

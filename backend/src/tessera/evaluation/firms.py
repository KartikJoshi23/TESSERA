"""The loaded records, in the one shape the dataset builders need.

Every builder reads facts through here, so strata and scenarios come from the snapshots the tools
search and from nowhere else. A firm built from a DFSA record is marked restricted, and everything
made from it carries that mark to ``datasets/restricted/``.
"""

from __future__ import annotations

from dataclasses import dataclass

from tessera.baseline.rules_only import REGISTER_WORDS
from tessera.data.registry import DataRegistry
from tessera.data.schemas import (
    CmaLicensedRecord,
    CmaWarningRecord,
    DfsaAlertFact,
    DfsaRegisterFact,
    VaraRegisterRecord,
    VaraUnlicensedRecord,
)
from tessera.knowledge import ActivityTaxonomy
from tessera.normalize.domains import registrable_domain

_LEGAL_ENDINGS = (
    "l.l.c.",
    "llc",
    "fze",
    "fzco",
    "pjsc",
    "(difc) limited",
    "limited",
    "ltd",
)


@dataclass(frozen=True)
class Firm:
    """One register entry."""

    regulator: str
    record_id: str
    name: str
    status: str  # "active", "ipa", "withdrawn" or "suspended"
    reference: str | None
    domain: str | None
    phone: str | None
    email_domain: str | None
    address: str | None
    covers: tuple[str, ...]
    aliases: tuple[str, ...]
    restricted: bool

    @property
    def covers_virtual(self) -> bool:
        return any(code.startswith("VA.") for code in self.covers)

    @property
    def short_name(self) -> str:
        """The name as an offer would loosely use it, without its legal ending."""
        lowered = self.name.casefold().rstrip()
        for ending in _LEGAL_ENDINGS:
            if lowered.endswith(ending):
                return self.name[: len(self.name) - len(ending)].rstrip(" ,.")
        return self.name


@dataclass(frozen=True)
class Listed:
    """One entry on a warning, unlicensed or alert list."""

    source_id: str
    record_id: str
    name: str | None
    contacts: tuple[str, ...]
    category: str
    reference: str | None
    restricted: bool


def _words_cover(activities: list[str], code: str) -> bool:
    joined = " ".join(activities).casefold()
    return any(word in joined for word in REGISTER_WORDS.get(code, ()))


def _covers(activities: list[str], taxonomy: ActivityTaxonomy) -> tuple[str, ...]:
    return tuple(a.code for a in taxonomy.activities if _words_cover(activities, a.code))


def _cma(record: CmaLicensedRecord, taxonomy: ActivityTaxonomy) -> Firm | None:
    if not record.name_en:
        return None
    return Firm(
        regulator="CMA",
        record_id=record.record_id,
        name=record.name_en,
        status="active" if (record.status or "").casefold() == "active" else "unknown",
        reference=record.licence_no,
        domain=registrable_domain(record.website) if record.website else None,
        phone=record.phone,
        email_domain=None,
        address=None,
        covers=_covers(record.activities, taxonomy),
        aliases=tuple(record.aliases),
        restricted=False,
    )


def _vara(record: VaraRegisterRecord, taxonomy: ActivityTaxonomy) -> Firm:
    return Firm(
        regulator="VARA",
        record_id=record.record_id,
        name=record.entity_name,
        status={"LICENSED": "active", "IPA": "ipa"}.get(record.status, "unknown"),
        reference=record.licence_ref,
        domain=registrable_domain(record.website) if record.website else None,
        phone=None,
        email_domain=None,
        address=None,
        covers=_covers(record.activities, taxonomy) if record.status == "LICENSED" else (),
        aliases=tuple(record.aliases),
        restricted=False,
    )


def _dfsa(record: DfsaRegisterFact, taxonomy: ActivityTaxonomy) -> Firm:
    covered, _ = taxonomy.dfsa_scope(record.permitted_services)
    return Firm(
        regulator="DFSA",
        record_id=record.record_id,
        name=record.firm_name,
        status={"authorised": "active"}.get(record.status, record.status),
        reference=record.frn,
        domain=registrable_domain(record.website) if record.website else None,
        phone=record.phone,
        email_domain=record.email_domains[0] if record.email_domains else None,
        address=record.address,
        covers=tuple(covered),
        aliases=tuple(record.aliases),
        restricted=True,
    )


def _warning(record: CmaWarningRecord) -> Listed:
    return Listed(
        source_id="cma_warnings",
        record_id=record.record_id,
        name=record.entity_name,
        contacts=tuple(record.domains_),
        category="warning",
        reference=None,
        restricted=False,
    )


def _unlicensed(record: VaraUnlicensedRecord) -> Listed:
    return Listed(
        source_id="vara_unlicensed",
        record_id=record.record_id,
        name=record.entity_name,
        contacts=tuple(record.domains_),
        category="unlicensed",
        reference=None,
        restricted=False,
    )


def _alert(record: DfsaAlertFact) -> Listed:
    return Listed(
        source_id="dfsa_alerts",
        record_id=record.record_id,
        name=record.firm_named,
        contacts=tuple(record.contact_points_named),
        category=record.category,
        reference=record.frn_named,
        restricted=True,
    )


@dataclass(frozen=True)
class World:
    """Everything the snapshots hold, ready for sampling."""

    firms: tuple[Firm, ...]
    listed: tuple[Listed, ...]
    activity_codes: tuple[str, ...]

    def of(self, regulator: str) -> list[Firm]:
        return [firm for firm in self.firms if firm.regulator == regulator]

    def alerts(self, *categories: str) -> list[Listed]:
        return [entry for entry in self.listed if entry.category in categories]


def load_world(registry: DataRegistry, taxonomy: ActivityTaxonomy) -> World:
    firms: list[Firm] = []
    listed: list[Listed] = []
    for record in registry.table("cma_licensed").records:
        if isinstance(record, CmaLicensedRecord) and (firm := _cma(record, taxonomy)):
            firms.append(firm)
    for record in registry.table("vara_register").records:
        if isinstance(record, VaraRegisterRecord):
            firms.append(_vara(record, taxonomy))
    for record in registry.table("cma_warnings").records:
        if isinstance(record, CmaWarningRecord):
            listed.append(_warning(record))
    for record in registry.table("vara_unlicensed").records:
        if isinstance(record, VaraUnlicensedRecord):
            listed.append(_unlicensed(record))
    if registry.restricted_allowed:
        for record in registry.table("dfsa_register").records:
            if isinstance(record, DfsaRegisterFact):
                firms.append(_dfsa(record, taxonomy))
        for record in registry.table("dfsa_alerts").records:
            if isinstance(record, DfsaAlertFact):
                listed.append(_alert(record))
    return World(tuple(firms), tuple(listed), tuple(a.code for a in taxonomy.activities))

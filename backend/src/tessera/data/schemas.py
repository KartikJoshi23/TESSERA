"""Normalised record schemas, one model per data source.

Lists inside hand-recorded CSV cells are separated by semicolons. Blank cells become ``None``.
DFSA models also report the restricted values they hold, which the masking gateway needs.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from tessera.governance.masking import RestrictedValue, classify_value


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _split_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.replace("\n", ";").split(";") if item.strip()]
    return value


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _upper(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


def _lower(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


OptStr = Annotated[str | None, BeforeValidator(_blank_to_none)]
OptDate = Annotated[date | None, BeforeValidator(_blank_to_none)]
StrList = Annotated[list[str], BeforeValidator(_split_list)]
ReqStr = Annotated[str, BeforeValidator(_strip), Field(min_length=1)]


class BaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: ReqStr

    def names(self) -> list[str]:
        """Names to match against, primary name first."""
        return []

    def domains(self) -> list[str]:
        return []

    def phones(self) -> list[str]:
        return []

    def emails(self) -> list[str]:
        return []

    def restricted_values(self) -> list[RestrictedValue]:
        return []


class CmaLicensedRecord(BaseRecord):
    """One row of the CMA "Export To Excel" file (columns mapped by the adapter)."""

    name_en: OptStr = None
    name_ar: OptStr = None
    licence_no: OptStr = None
    category: OptStr = None
    activities: StrList = Field(default_factory=list)
    status: OptStr = None
    emirate: OptStr = None
    website: OptStr = None
    phone: OptStr = None
    email: OptStr = None
    aliases: StrList = Field(default_factory=list)
    raw: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _has_name(self) -> CmaLicensedRecord:
        if not (self.name_en or self.name_ar):
            raise ValueError("a licensed company needs an English or Arabic name")
        return self

    def names(self) -> list[str]:
        return [n for n in (self.name_en, self.name_ar, *self.aliases) if n]

    def domains(self) -> list[str]:
        return [self.website] if self.website else []

    def phones(self) -> list[str]:
        return [self.phone] if self.phone else []

    def emails(self) -> list[str]:
        return [self.email] if self.email else []


class CmaWarningRecord(BaseRecord):
    entity_name: ReqStr
    warning_date: OptDate = None
    domains_: StrList = Field(default_factory=list, alias="domains")
    phones_: StrList = Field(default_factory=list, alias="phones")
    emails_: StrList = Field(default_factory=list, alias="emails")
    notes: OptStr = None
    page_url: OptStr = None
    recorded_by: ReqStr
    recorded_on: date

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    def names(self) -> list[str]:
        return [self.entity_name]

    def domains(self) -> list[str]:
        return list(self.domains_)

    def phones(self) -> list[str]:
        return list(self.phones_)

    def emails(self) -> list[str]:
        return list(self.emails_)


class VaraRegisterRecord(BaseRecord):
    entity_name: ReqStr
    status: Annotated[Literal["LICENSED", "IPA", "OTHER"], BeforeValidator(_upper)]
    licence_ref: OptStr = None
    activities: StrList = Field(default_factory=list)
    website: OptStr = None
    aliases: StrList = Field(default_factory=list)
    page_url: OptStr = None
    recorded_by: ReqStr
    recorded_on: date

    def names(self) -> list[str]:
        return [self.entity_name, *self.aliases]

    def domains(self) -> list[str]:
        return [self.website] if self.website else []


class VaraUnlicensedRecord(BaseRecord):
    entity_name: ReqStr
    domains_: StrList = Field(default_factory=list, alias="domains")
    date_listed: OptDate = None
    page_url: OptStr = None
    recorded_by: ReqStr
    recorded_on: date

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    def names(self) -> list[str]:
        return [self.entity_name]

    def domains(self) -> list[str]:
        return list(self.domains_)


DfsaStatus = Literal["authorised", "withdrawn", "suspended", "other"]
#: Parts of an address that say only where it is. A zone identifies nobody, and the Jurisdiction
#: agent needs it, so these stay visible when the rest of an address is masked.
_GENERIC_ADDRESS_PARTS = frozenset(
    {
        "abu dhabi",
        "abu dhabi global market",
        "adgm",
        "ajman",
        "difc",
        "dubai",
        "dubai international financial centre",
        "fujairah",
        "ras al khaimah",
        "sharjah",
        "uae",
        "umm al quwain",
        "united arab emirates",
    }
)
DfsaAlertCategory = Literal[
    "impersonated_authorised_firm",
    "false_claim_of_authorisation",
    "regulator_impersonation",
    "unauthorised_firm",
    "other",
]


class DfsaRegisterFact(BaseRecord):
    """Minimal facts a person recorded from the DFSA Public Register (restricted)."""

    firm_name: ReqStr
    frn: OptStr = None
    status: Annotated[DfsaStatus, BeforeValidator(_lower)]
    permitted_services: StrList = Field(default_factory=list)
    address: OptStr = None
    website: OptStr = None
    phone: OptStr = None
    email_domains: StrList = Field(default_factory=list)
    aliases: StrList = Field(default_factory=list)
    recorded_by: ReqStr
    recorded_on: date

    def names(self) -> list[str]:
        return [self.firm_name, *self.aliases]

    def domains(self) -> list[str]:
        return [d for d in (self.website, *self.email_domains) if d]

    def phones(self) -> list[str]:
        return [self.phone] if self.phone else []

    def restricted_values(self) -> list[RestrictedValue]:
        ref = f"dfsa_register:{self.record_id}"
        values = [RestrictedValue(name, "firm_name", ref) for name in self.names()]
        if self.frn:
            values.append(RestrictedValue(self.frn, "reference", ref))
        values += [RestrictedValue(d.lstrip("@"), "domain", ref) for d in self.domains()]
        values += [RestrictedValue(p, "phone", ref) for p in self.phones()]
        for part in (self.address or "").split(","):
            if part.strip().casefold() not in _GENERIC_ADDRESS_PARTS:
                values.append(RestrictedValue(part.strip(), "address", ref))
        return values


class DfsaAlertFact(BaseRecord):
    """Minimal facts a person recorded from a 2026 DFSA alert (restricted)."""

    alert_date: date
    category: Annotated[DfsaAlertCategory, BeforeValidator(_lower)]
    firm_named: OptStr = None
    frn_named: OptStr = None
    contact_points_named: StrList = Field(default_factory=list)
    legitimate_contacts_stated: StrList = Field(default_factory=list)
    recorded_by: ReqStr
    recorded_on: date

    def names(self) -> list[str]:
        return [self.firm_named] if self.firm_named else []

    def restricted_values(self) -> list[RestrictedValue]:
        ref = f"dfsa_alerts:{self.record_id}"
        values = [RestrictedValue(name, "firm_name", ref) for name in self.names()]
        if self.frn_named:
            values.append(RestrictedValue(self.frn_named, "reference", ref))
        for contact in (*self.contact_points_named, *self.legitimate_contacts_stated):
            kind = classify_value(contact)
            if kind is not None:
                values.append(RestrictedValue(contact, kind, ref))
        return values


SOURCE_SCHEMAS: dict[str, type[BaseRecord]] = {
    "cma_licensed": CmaLicensedRecord,
    "cma_warnings": CmaWarningRecord,
    "vara_register": VaraRegisterRecord,
    "vara_unlicensed": VaraUnlicensedRecord,
    "dfsa_register": DfsaRegisterFact,
    "dfsa_alerts": DfsaAlertFact,
}

"""Contact points extracted from an offer, and the role each kind plays in a decision."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ContactKind(StrEnum):
    URL = "url"
    DOMAIN = "domain"
    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    SOCIAL_HANDLE = "social_handle"
    IBAN = "iban"
    WALLET = "wallet"
    ADDRESS = "address"
    LICENCE_REF = "licence_ref"
    SHORT_LINK = "short_link"


class ContactRole(StrEnum):
    """§4.7: whether a contact detail can decide a result."""

    DECIDING = "deciding"
    REPORTED = "reported"
    NOT_COMPARABLE = "not_comparable"


#: Mirrors ``contact_roles`` in policies/decision_policy.yaml (a test keeps them in sync).
DEFAULT_CONTACT_ROLES: dict[ContactKind, ContactRole] = {
    ContactKind.URL: ContactRole.DECIDING,
    ContactKind.DOMAIN: ContactRole.DECIDING,
    ContactKind.EMAIL: ContactRole.DECIDING,
    ContactKind.PHONE: ContactRole.DECIDING,
    ContactKind.WHATSAPP: ContactRole.DECIDING,
    ContactKind.IBAN: ContactRole.DECIDING,
    ContactKind.WALLET: ContactRole.DECIDING,
    ContactKind.ADDRESS: ContactRole.REPORTED,
    ContactKind.TELEGRAM: ContactRole.REPORTED,
    ContactKind.SOCIAL_HANDLE: ContactRole.REPORTED,
    ContactKind.LICENCE_REF: ContactRole.REPORTED,
    ContactKind.SHORT_LINK: ContactRole.NOT_COMPARABLE,
}


class ContactPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    cp_id: str
    kind: ContactKind
    raw: str
    normalized: str
    start: int
    end: int
    role: ContactRole
    detail: dict[str, str] = Field(default_factory=dict)

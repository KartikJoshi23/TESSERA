"""Deterministic tools: the only code that creates evidence (ADR-0002).

Every tool is read-only, offline and deterministic. Lookups always create evidence, whether a
match or an explicit no-match, so absence is checkable as well as presence.
"""

from tessera.tools.context import ToolContext
from tessera.tools.domain_analysis import compare_domain, compare_domains
from tessera.tools.extract import extract_contact_points
from tessera.tools.lookups import (
    cma_register_lookup,
    cma_warnings_lookup,
    dfsa_facts_lookup,
    official_contacts_for,
    reverse_contact_lookup,
    vara_register_lookup,
    vara_unlicensed_lookup,
)
from tessera.tools.payment_analysis import analyse_payment
from tessera.tools.phone_analysis import analyse_phone
from tessera.tools.rule_cards import get_rule_card

__all__ = [
    "ToolContext",
    "analyse_payment",
    "analyse_phone",
    "cma_register_lookup",
    "cma_warnings_lookup",
    "compare_domain",
    "compare_domains",
    "dfsa_facts_lookup",
    "extract_contact_points",
    "get_rule_card",
    "official_contacts_for",
    "reverse_contact_lookup",
    "vara_register_lookup",
    "vara_unlicensed_lookup",
]

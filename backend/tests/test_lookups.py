from tessera.governance.links import DFSA_HOMEPAGE
from tessera.protocol.evidence import RESTRICTED_SAFE_FIELDS, EvidenceKind
from tessera.tools import (
    ToolContext,
    analyse_payment,
    analyse_phone,
    cma_register_lookup,
    cma_warnings_lookup,
    compare_domain,
    dfsa_facts_lookup,
    get_rule_card,
    official_contacts_for,
    reverse_contact_lookup,
    vara_register_lookup,
    vara_unlicensed_lookup,
)


def test_cma_lookup_by_name(ctx):
    result = cma_register_lookup(ctx, name="Falcon Ridge Securities LLC")
    best = result.summary["matches"][0]
    assert best["record_id"] == "CMA-L-1001" and best["match_type"] == "exact"
    evidence = result.evidence[0]
    assert evidence.kind is EvidenceKind.REGISTER_ENTRY
    assert evidence.display_link.startswith("https://www.uaecma.gov.ae/en/open-data/")
    assert evidence.snapshot_id and evidence.snapshot_date


def test_cma_category_5_record_is_returned_with_its_category(ctx):
    best = cma_register_lookup(ctx, licence_no="cma-l-1002").summary["matches"][0]
    assert best["category"] == "Category 5" and best["match_type"] == "reference"


def test_no_match_still_mints_evidence(ctx):
    result = cma_register_lookup(ctx, name="Nonexistent Holdings")
    assert result.summary["matches"] == []
    assert result.evidence[0].kind is EvidenceKind.NO_MATCH
    assert result.summary["no_match_evidence_id"] == result.evidence[0].evidence_id


def test_vara_lookup_keeps_ipa_separate(ctx):
    result = vara_register_lookup(ctx, name="Saffron Chain Custody")
    assert result.summary["matches"][0]["status"] == "IPA"
    assert result.summary["in_principle_approval"] and not result.summary["licensed"]


def test_unlicensed_list_by_domain(ctx):
    result = vara_unlicensed_lookup(ctx, domain="https://mirage-coin.example/signup")
    assert result.summary["matches"][0]["record_id"] == "VARA-U-0001"
    assert result.evidence[0].kind is EvidenceKind.UNLICENSED_ENTRY


def test_warning_lookup_by_email(ctx):
    result = cma_warnings_lookup(ctx, email="support@goldendune-fx.example")
    assert result.summary["matches"][0]["record_id"] == "CMA-W-0001"


def test_reverse_lookup_reaches_public_lists_and_restricted_alerts(ctx):
    warning = reverse_contact_lookup(ctx, "support@goldendune-fx.example")
    assert [h["source_id"] for h in warning.summary["hits"]] == ["cma_warnings"]
    alert = reverse_contact_lookup(ctx, "https://lumencrest-capital.example/login")
    hit = next(h for h in alert.summary["hits"] if h["source_id"] == "dfsa_alerts")
    assert hit["matched_on"] == "contact_named" and alert.restricted
    restricted = [e for e in alert.evidence if e.restricted]
    assert restricted and all(e.display_link == DFSA_HOMEPAGE for e in restricted)


def test_dfsa_lookup_in_research_mode(ctx):
    result = dfsa_facts_lookup(ctx, frn="F000000")
    register = result.summary["register_matches"][0]
    assert register["status"] == "authorised"
    assert "Advising on Financial Products" in register["permitted_services"]
    assert result.summary["alert_matches"][0]["matched_on"] == "frn_named"
    assert result.restricted
    for evidence in result.evidence:
        assert evidence.restricted and evidence.display_link == DFSA_HOMEPAGE
        assert set(evidence.fields) <= RESTRICTED_SAFE_FIELDS  # no DFSA values in evidence


def test_dfsa_lookup_in_demo_mode_loads_nothing(demo_ctx):
    result = dfsa_facts_lookup(demo_ctx, name="Lumen Crest Capital")
    assert result.summary["available"] is False
    assert "www.dfsa.ae" in result.summary["message"]
    assert result.evidence == ()
    assert demo_ctx.registry.restricted_values() == []


def test_evidence_ids_are_deterministic_and_case_scoped(populated_settings):
    first = ToolContext.create("case-A", populated_settings)
    second = ToolContext.create("case-B", populated_settings)
    a1 = cma_register_lookup(first, name="Falcon Ridge Securities").evidence[0].evidence_id
    a2 = cma_register_lookup(first, name="Falcon Ridge Securities").evidence[0].evidence_id
    b1 = cma_register_lookup(second, name="Falcon Ridge Securities").evidence[0].evidence_id
    assert a1 == a2 and a1 != b1


def test_official_contacts_for_a_register_entry(ctx):
    entry = cma_register_lookup(ctx, name="Falcon Ridge Securities").evidence[0]
    contacts = official_contacts_for(ctx, entry).summary
    assert contacts["domains"] == ["falconridge.example"]
    assert contacts["phones"] == ["+97140001001"]
    assert contacts["email_domains"] == ["falconridge.example"]


def test_sources_without_snapshots_report_unavailable(empty_ctx):
    result = cma_register_lookup(empty_ctx, name="anything")
    assert result.summary["available"] is False and result.evidence == ()


def test_domain_comparison_tool_against_restricted_record(ctx):
    official = dfsa_facts_lookup(ctx, frn="F000000").evidence[0]
    result = compare_domain(ctx, "lumencrest-capital.example", "lumencrest.example", official)
    evidence = result.evidence[0]
    assert result.summary["lookalike"] and evidence.restricted
    assert set(evidence.fields) <= RESTRICTED_SAFE_FIELDS


def test_phone_and_payment_analysis(ctx):
    phone = analyse_phone(ctx, "04-000-1001", ["+971 4 000 1001"])
    assert phone.evidence[0].fields["equal_to_official"] is True
    payment = analyse_payment(
        ctx,
        iban="AE07 0331 2345 6789 0123 456",
        beneficiary="XYZ General Trading",
        entity_names=["Falcon Ridge Securities L.L.C."],
    )
    fields = payment.evidence[0].fields
    assert fields["iban_valid"] is True and fields["iban_country"] == "AE"
    assert fields["beneficiary_matches"] is False
    wallet = analyse_payment(ctx, wallet="T" + "Q" * 33)
    assert wallet.evidence[0].fields["wallet_requested"] is True


def test_rule_cards_are_evidence(ctx):
    single = get_rule_card(ctx, rule_id="SCOPE-CMA-01")
    assert single.evidence[0].kind is EvidenceKind.RULE_CARD
    assert single.evidence[0].fields["rule_id"] == "SCOPE-CMA-01"
    vara = {e.fields["rule_id"] for e in get_rule_card(ctx, regulator="VARA").evidence}
    assert {"JUR-01", "SCOPE-VARA-01", "SCOPE-VARA-02", "CLONE-01"} <= vara


def test_registry_exposes_restricted_values_for_masking(ctx):
    values = {(v.kind, v.value) for v in ctx.registry.restricted_values()}
    assert ("reference", "F000000") in values
    assert ("domain", "lumencrest-capital.example") in values
    assert ("firm_name", "Lumen Crest Capital (DIFC) Limited") in values

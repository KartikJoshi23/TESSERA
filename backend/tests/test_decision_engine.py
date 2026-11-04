"""The decision-policy engine on the fictional smoke set, and on the ways a case can go wrong."""

import json
from datetime import timedelta

import pytest

from tessera.devdata import FICTION_DATE, load_smoke_cases
from tessera.governance.policies import load_decision_policy
from tessera.orchestration.decision import _regulator_named, derive_decision
from tessera.orchestration.support import ClaimChecker, official_status
from tessera.protocol.claims import (
    ActivityClaim,
    AlertHit,
    ContactAssessment,
    CoverageGap,
    OfferClaim,
    RegisterMatch,
)
from tessera.protocol.common import AgentId, ResultCode
from tessera.protocol.conflicts import ConflictType
from tessera.protocol.evidence import EvidenceKind, mint_evidence
from tessera.protocol.messages import MessageDraft, Performative

from .conftest import REPO_ROOT
from .oracle import ORACLE, run_oracle

CASES = {case.id: case for case in load_smoke_cases(REPO_ROOT)}


def decide(setup, **kwargs):
    return derive_decision(setup.env, today=FICTION_DATE, **kwargs)


def oracle_case(harness, key):
    setup = harness(CASES[key].offer().text, case_id=key)
    run_oracle(setup, key)
    return setup


@pytest.mark.parametrize("key", sorted(ORACLE))
def test_a_careful_crew_reaches_every_gold_result_for_the_gold_reasons(harness, key):
    case = CASES[key]
    decision = decide(oracle_case(harness, key))
    assert decision.result is case.gold_label, decision.summary()
    reasons = (
        decision.hard_conflict_ids
        if case.gold_label is ResultCode.CONFLICTS
        else decision.unverified_reasons
    )
    assert set(reasons) == set(case.gold_reasons), decision.summary()


def test_every_smoke_case_is_covered_by_the_oracle():
    assert set(ORACLE) == set(CASES)


# ------------------------------------------------------------------- what evidence can do


def test_a_consistent_case_needs_every_condition(harness):
    decision = decide(oracle_case(harness, "S01"))
    assert decision.result is ResultCode.CONSISTENT and all(decision.conditions.values())
    assert decision.unverified_reasons == ()


def test_a_finding_with_invented_evidence_counts_for_nothing(harness):
    setup = oracle_case(harness, "S20")
    assert decide(setup).result is ResultCode.UNVERIFIED
    setup.board.post_finding(
        AgentId.CMA,
        RegisterMatch(regulator="CMA", entity_evidence_id="E-feedfacefeedface", match_type="exact"),
        evidence_ids=["E-feedfacefeedface"],
    )
    decision = decide(setup)
    assert decision.result is ResultCode.UNVERIFIED and not decision.conditions["K7"]
    assert "U7" in decision.unverified_reasons


def test_a_hard_conflict_with_invented_evidence_does_not_count(harness):
    setup = oracle_case(harness, "S20")
    setup.board.post_finding(
        AgentId.VARA,
        AlertHit(
            source_id="vara_unlicensed",
            alert_evidence_id="E-feedfacefeedface",
            about="entity_unauthorised",
            matched_on="name",
        ),
        evidence_ids=["E-feedfacefeedface"],
    )
    assert decide(setup).hard_conflicts == ()


def test_a_claim_that_copies_no_words_cannot_create_a_conflict(harness):
    """HC3 needs a claim the offer really makes."""
    setup = harness(CASES["S20"].offer().text, case_id="S20")
    run_oracle(setup, "S20")
    setup.board.post_finding(AgentId.JUR, OfferClaim(kind="regulator", value="VARA"))
    assert decide(setup).hard_conflicts == ()


@pytest.mark.parametrize(
    ("claim", "code"),
    [
        ("DFSA", "DFSA"),
        ("regulated by the DFSA", "DFSA"),
        ("the Dubai Financial Services Authority", "DFSA"),
        ("licensed by the SCA", "CMA"),
        ("Securities and Commodities Authority", "CMA"),
        ("UAE Financial Trade Authority", None),
        ("ESCAPE Markets Board", None),  # "sca" inside another word is not the SCA
    ],
)
def test_a_regulator_can_be_named_in_a_phrase(claim, code):
    names = load_decision_policy(REPO_ROOT / "policies").regulator_names
    assert _regulator_named(claim, names) == code


@pytest.mark.parametrize(
    ("shown", "status"),
    [
        ("Active", "active"),
        (" ACTIVE ", "active"),
        ("Inactive", None),
        ("Not Active", None),
        ("Suspended", "suspended"),
        ("Licence cancelled", "withdrawn"),
        ("", None),
    ],
)
def test_a_cma_status_is_read_exactly(shown, status):
    record = mint_evidence(
        case_id="c",
        source_id="cma_licensed",
        kind=EvidenceKind.REGISTER_ENTRY,
        locator="x",
        fields={"status": shown},
        minted_by="test",
    )
    assert official_status(record, {}) == status


def test_a_look_alike_of_another_official_domain_is_not_a_conflict(harness):
    """A contact that matches one official domain can resemble another one."""
    setup = oracle_case(harness, "S01")
    contact = setup.board.live_findings("contact_assessment")[0]
    assert contact.assertion.status == "matches_official"
    evidence = next(e for e in setup.board.evidence.values() if e.minted_by == "compare_domain")
    setup.board.evidence[evidence.evidence_id] = evidence.model_copy(
        update={"fields": {**evidence.fields, "lookalike": True}}
    )
    assert decide(setup).hard_conflicts == ()


def test_an_ipa_entry_covers_nothing_whatever_a_model_says(harness):
    setup = oracle_case(harness, "S11")
    scope = setup.board.live_findings("licence_scope")[0]
    called_covered = scope.model_copy(
        update={"assertion": scope.assertion.model_copy(update={"covered": "yes"})}
    )
    setup.board.findings[scope.finding_id] = called_covered
    checker = ClaimChecker(setup.board, setup.env.ctx.sources, setup.env.facts_for)
    assert "covers no activity" in checker.problems(called_covered)[0]
    assert "HC4" in decide(setup).hard_conflict_ids  # the status alone is enough


def test_a_claimed_regulator_outside_coverage_rules_out_consistent(harness):
    setup = oracle_case(harness, "S01")
    words = setup.env.quote_evidence("Falcon Ridge")
    setup.board.post_finding(
        AgentId.JUR,
        OfferClaim(kind="regulator", value="Central Bank of the UAE"),
        evidence_ids=words,
    )
    decision = decide(setup)
    assert decision.result is ResultCode.UNVERIFIED and "U2" in decision.unverified_reasons


def test_a_contact_not_on_record_blocks_consistent_but_is_not_a_conflict(harness):
    decision = decide(oracle_case(harness, "S23"))
    assert decision.result is ResultCode.UNVERIFIED
    assert decision.hard_conflicts == () and "U3" in decision.unverified_reasons


def test_an_impersonation_alert_alone_does_not_block_a_matching_offer(harness):
    decision = decide(oracle_case(harness, "S04"))
    assert decision.result is ResultCode.CONSISTENT


def test_an_uncovered_regulator_rules_out_consistent(harness):
    setup = oracle_case(harness, "S01")
    setup.board.post_finding(
        AgentId.ORC, CoverageGap(regulator="CBUAE", reason="not covered in this phase")
    )
    from tessera.protocol.claims import Relevance

    setup.board.post_finding(AgentId.JUR, Relevance(regulator="CBUAE", status="possible"))
    decision = decide(setup)
    assert decision.result is ResultCode.UNVERIFIED and decision.unverified_reasons == ("U2",)


def test_an_offered_activity_with_no_scope_finding_cannot_be_consistent(harness):
    setup = oracle_case(harness, "S01")
    setup.board.post_finding(
        AgentId.JUR, ActivityClaim(code="VA.CUSTODY"), evidence_ids=setup.env.quote_evidence("FX")
    )
    decision = decide(setup)
    assert decision.result is ResultCode.UNVERIFIED and decision.unverified_reasons == ("U9",)


def test_an_offer_with_no_contact_details_proves_nothing(harness):
    setup = harness("Falcon Ridge Securities L.L.C. offers spot FX and CFD trading accounts.")
    from .oracle import Facts, Oracle

    Oracle(
        setup,
        Facts(
            (("DER.FX_CFD", "spot FX and CFD trading"),),
            {"CMA": "primary"},
            firm="Falcon Ridge Securities L.L.C.",
        ),
    ).run()
    decision = decide(setup)
    assert not decision.conditions["K4"] and decision.result is ResultCode.UNVERIFIED


# ------------------------------------------------------------------- failures and limits


def test_a_stale_snapshot_rules_out_consistent(harness):
    setup = oracle_case(harness, "S01")
    late = FICTION_DATE + timedelta(days=61)
    decision = derive_decision(setup.env, today=late)
    assert decision.result is ResultCode.UNVERIFIED and "U7" in decision.unverified_reasons
    on_time = derive_decision(setup.env, today=FICTION_DATE + timedelta(days=60))
    assert on_time.result is ResultCode.CONSISTENT


def test_a_failed_agent_rules_out_consistent(harness):
    setup = oracle_case(harness, "S01")
    setup.board.note_failure(AgentId.VARA, "model_error")
    decision = decide(setup)
    assert decision.result is ResultCode.UNVERIFIED and "U7" in decision.unverified_reasons


def test_a_failed_agent_does_not_hide_a_hard_conflict(harness):
    setup = oracle_case(harness, "S15")
    setup.board.note_failure(AgentId.VARA, "model_error")
    assert decide(setup).result is ResultCode.CONFLICTS


def test_a_veto_that_stands_is_listed(harness):
    decision = decide(oracle_case(harness, "S20"), veto_standing=True)
    assert "U6" in decision.unverified_reasons


def test_several_register_entries_are_ambiguous(harness):
    setup = oracle_case(harness, "S01")
    other = setup.env.belt.execute(
        "vara_register_lookup",
        '{"name": "Coral Ledger Exchange FZE"}',
        allowed=("vara_register_lookup",),
        actor=AgentId.VARA,
    )
    import json

    evidence = json.loads(other[0])["matches"][0]["evidence_id"]
    setup.board.post_finding(
        AgentId.VARA,
        RegisterMatch(regulator="VARA", entity_evidence_id=evidence, match_type="exact"),
        evidence_ids=[evidence],
    )
    decision = decide(setup)
    assert decision.result is ResultCode.UNVERIFIED and "U4" in decision.unverified_reasons


def test_a_fuzzy_match_needs_a_second_identifier(harness):
    setup = oracle_case(harness, "S01")
    match = setup.board.live_findings("register_match")[0]
    assert decide(setup).conditions["K1"]
    setup.board.findings[match.finding_id] = match.model_copy(
        update={"assertion": match.assertion.model_copy(update={"match_type": "fuzzy"})}
    )
    decision = decide(setup)
    # The evidence says the tool found an exact match, so the altered finding also loses K7.
    assert not decision.conditions["K1"] and not decision.conditions["K7"]


# ------------------------------------------------------------------- conversation


def challenge(setup, finding):
    return setup.board.send(
        MessageDraft(
            sender=AgentId.REC,
            recipients=(finding.author,),
            performative=Performative.CHALLENGE,
            refs=(finding.finding_id,),
            rule_ids=("CLONE-01",),
            body={"question": "Why?"},
        )
    )


def test_an_unanswered_challenge_stops_a_finding_supporting_consistent(harness):
    setup = oracle_case(harness, "S01")
    contact = setup.board.live_findings("contact_assessment")[0]
    challenge(setup, contact)
    decision = decide(setup)
    assert decision.result is ResultCode.UNVERIFIED and not decision.conditions["K4"]


def test_an_unanswered_challenge_does_not_remove_a_hard_conflict(harness):
    """Otherwise a challenge alone could turn a conflict into something more reassuring."""
    setup = oracle_case(harness, "S15")
    contact = setup.board.live_findings("contact_assessment")[0]
    challenge(setup, contact)
    assert decide(setup).result is ResultCode.CONFLICTS


def test_an_unresolved_conflict_takes_its_hard_conflict_with_it(harness):
    """P7: a conflict stands only if it does not rest on the unresolved point."""
    setup = oracle_case(harness, "S15")
    contact = setup.board.live_findings("contact_assessment")[0]
    setup.board.add_conflict(ConflictType.C4, [contact.finding_id])
    decision = decide(setup)
    assert decision.result is ResultCode.UNVERIFIED and "U5" in decision.unverified_reasons


def test_a_resolution_cannot_remove_a_valid_finding(harness):
    """The Reconciler closes conflicts. It cannot overrule evidence by argument."""
    setup = oracle_case(harness, "S15")
    contact = setup.board.live_findings("contact_assessment")[0]
    conflict = setup.board.add_conflict(ConflictType.C4, [contact.finding_id])
    setup.board.resolve_conflict(
        conflict.conflict_id, outcome="overturned", precedence_rule="P1", winning_finding_ids=()
    )
    assert decide(setup).result is ResultCode.CONFLICTS


def test_a_contact_marked_official_needs_a_comparison_of_that_contact(harness):
    """An agent cannot call one contact official by citing the comparison of another."""
    setup = oracle_case(harness, "S23")
    assessed = setup.board.live_findings("contact_assessment")[0]
    entry = assessed.assertion.official_evidence_id
    other = setup.env.belt.execute(
        "compare_domain",
        f'{{"offer_domain": "falconridge.example", "official_domain": "falconridge.example", '
        f'"official_evidence_id": "{entry}"}}',
        allowed=("compare_domain",),
        actor=AgentId.CLN,
    )
    import json

    setup.board.post_finding(
        AgentId.CLN,
        ContactAssessment(
            cp_id=assessed.assertion.cp_id,
            status="matches_official",
            official_evidence_id=entry,
        ),
        evidence_ids=[entry, json.loads(other[0])["evidence_id"]],
    )
    assert decide(setup).result is ResultCode.UNVERIFIED


def test_a_listed_email_domain_counts_as_a_listed_contact(harness):
    """A list can name a domain, and an offer can use an address at that domain."""
    setup = harness("Write to help@goldendune-fx.example today.", case_id="S13")
    point = setup.board.case.contact_points[0]
    content, ok = setup.env.belt.execute(
        "cma_warnings_lookup",
        '{"email": "help@goldendune-fx.example"}',
        allowed=("cma_warnings_lookup",),
        actor=AgentId.CMA,
    )
    assert ok
    hit = json.loads(content)["matches"][0]
    assert hit["matched_on"] == "email_domain"
    finding = setup.board.post_finding(
        AgentId.CLN,
        ContactAssessment(cp_id=point.cp_id, status="alert_listed"),
        evidence_ids=[hit["evidence_id"]],
    )
    checker = ClaimChecker(setup.board, setup.env.ctx.sources, setup.env.facts_for)
    assert checker.problems(finding) == []
    assert decide(setup).hard_conflict_ids == ("HC1",)

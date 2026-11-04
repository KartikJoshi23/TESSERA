"""The Conflict Detector's rules C1–C7, and how conflicts open, settle and stay closed."""

from tessera.devdata import FICTION_DATE, load_smoke_cases
from tessera.orchestration.decision import DecisionEngine
from tessera.orchestration.detector import run_detector
from tessera.protocol.claims import AlertHit, ContactAssessment, Relevance
from tessera.protocol.common import AgentId
from tessera.protocol.conflicts import ConflictStatus, ConflictType
from tessera.protocol.messages import MessageDraft, Performative

from .conftest import REPO_ROOT
from .oracle import Facts, Oracle, run_oracle

CASES = {case.id: case for case in load_smoke_cases(REPO_ROOT)}


def detect(setup):
    return run_detector(setup.env, DecisionEngine(setup.env, FICTION_DATE))


def types_in(conflicts):
    return sorted(conflict.type.value for conflict in conflicts)


def oracle_case(harness, key):
    setup = harness(CASES[key].offer().text, case_id=key)
    run_oracle(setup, key)
    return setup


def test_a_clean_case_has_no_conflicts(harness):
    assert detect(oracle_case(harness, "S01")) == []


def test_relevance_splits_are_conflicts_but_shades_of_relevant_are_not(harness):
    setup = oracle_case(harness, "S01")
    setup.board.post_finding(AgentId.VARA, Relevance(regulator="VARA", status="possible"))
    conflicts = detect(setup)
    assert types_in(conflicts) == ["C1"]
    setup = oracle_case(harness, "S01")
    setup.board.post_finding(AgentId.CMA, Relevance(regulator="CMA", status="possible"))
    assert detect(setup) == []


def test_a_reference_number_of_another_firm_is_an_identity_conflict(harness):
    assert "C2" in types_in(detect(oracle_case(harness, "S16")))
    assert "C2" in types_in(detect(oracle_case(harness, "S19")))


def test_several_entries_are_an_identity_conflict(harness):
    setup = oracle_case(harness, "S01")
    Oracle(setup, Facts((), {}, firm="Coral Ledger Exchange FZE")).vara()
    assert "C2" in types_in(detect(setup))


def test_an_activity_outside_a_live_licence_is_a_scope_conflict(harness):
    assert types_in(detect(oracle_case(harness, "S10"))) == ["C3"]


def test_a_contact_called_official_but_named_on_a_list_is_a_contact_conflict(harness):
    setup = oracle_case(harness, "S01")
    warning = setup.env.belt.execute(
        "cma_warnings_lookup",
        '{"name": "Golden Dune Trading Platform"}',
        allowed=("cma_warnings_lookup",),
        actor=AgentId.CMA,
    )
    import json

    evidence = json.loads(warning[0])["matches"][0]["evidence_id"]
    setup.board.post_finding(
        AgentId.CMA,
        AlertHit(
            source_id="cma_warnings",
            alert_evidence_id=evidence,
            about="contact_listed",
            matched_on="domain",
        ),
        evidence_ids=[evidence],
    )
    assert "C4" in types_in(detect(setup))


def test_a_firm_on_a_register_and_in_an_impersonation_alert_is_a_conflict(harness):
    conflicts = detect(oracle_case(harness, "S09"))
    assert "C5" in types_in(conflicts) and "C3" in types_in(conflicts)


def test_a_finding_without_valid_evidence_is_a_conflict(harness):
    setup = oracle_case(harness, "S01")
    point = setup.board.case.contact_points[0]
    setup.board.post_finding(
        AgentId.CLN,
        ContactAssessment(cp_id=point.cp_id, status="alert_listed"),
        evidence_ids=["E-feedfacefeedface"],
    )
    conflicts = detect(setup)
    assert types_in(conflicts) == ["C6"]
    assert "no tool created" in conflicts[0].summary


def test_a_firm_on_a_different_register_than_claimed_is_a_conflict(harness):
    setup = harness("Coral Ledger Exchange FZE is licensed by the CMA. See coralledger.example.")
    Oracle(
        setup,
        Facts(
            (("VA.EXCHANGE", "Exchange"),),
            {"CMA": "possible", "VARA": "primary"},
            firm="Coral Ledger Exchange FZE",
            regulator=("CMA", "licensed by the CMA"),
        ),
    ).run()
    assert "C7" in types_in(detect(setup))


# ------------------------------------------------------------------- the life of a conflict


def split_on_relevance(harness):
    setup = harness(CASES["S01"].offer().text, case_id="S01")
    jurisdiction = setup.board.post_finding(
        AgentId.JUR, Relevance(regulator="VARA", status="not_indicated")
    )
    setup.board.post_finding(AgentId.VARA, Relevance(regulator="VARA", status="possible"))
    return setup, jurisdiction


def test_detection_is_idempotent(harness):
    setup = oracle_case(harness, "S09")
    first = detect(setup)
    assert first and detect(setup) == []
    assert len(setup.board.conflicts) == len(first)


def test_a_conflict_whose_trigger_has_gone_is_settled_without_a_model(harness):
    setup, jurisdiction = split_on_relevance(harness)
    conflict = detect(setup)[0]
    message = setup.board.send(
        MessageDraft(
            sender=AgentId.VARA,
            recipients=(AgentId.JUR,),
            performative=Performative.CHALLENGE,
            refs=(jurisdiction.finding_id,),
            rule_ids=("JUR-01",),
            body={"question": "Why not?"},
        )
    )
    setup.board.revise_finding(
        reply_to=message.msg_id,
        sender=AgentId.JUR,
        assertion=jurisdiction.assertion.model_copy(update={"status": "possible"}),
        rule_ids=("JUR-01",),
    )
    assert detect(setup) == []
    assert setup.board.conflicts[conflict.conflict_id].status is ConflictStatus.SETTLED
    assert setup.board.open_conflicts() == []
    assert setup.transport.payloads == []


def test_a_resolved_conflict_is_not_reopened(harness):
    setup = oracle_case(harness, "S10")
    conflict = detect(setup)[0]
    setup.board.resolve_conflict(conflict.conflict_id, outcome="upheld", precedence_rule="P3")
    assert detect(setup) == []
    assert setup.board.conflicts[conflict.conflict_id].status is ConflictStatus.RESOLVED


def test_conflicts_the_reconciler_opened_are_left_to_it(harness):
    setup = oracle_case(harness, "S01")
    finding = setup.board.live_findings("relevance")[0]
    conflict = setup.board.add_conflict(
        ConflictType.C1, [finding.finding_id], detected_by="REC", summary="Seen by the Reconciler."
    )
    assert detect(setup) == []
    assert setup.board.conflicts[conflict.conflict_id].status is ConflictStatus.OPEN


def test_settling_survives_replay(harness):
    from tessera.blackboard.board import Blackboard

    setup, jurisdiction = split_on_relevance(harness)
    detect(setup)
    message = setup.board.send(
        MessageDraft(
            sender=AgentId.VARA,
            recipients=(AgentId.JUR,),
            performative=Performative.CHALLENGE,
            refs=(jurisdiction.finding_id,),
            rule_ids=("JUR-01",),
            body={"question": "Why not?"},
        )
    )
    setup.board.revise_finding(
        reply_to=message.msg_id,
        sender=AgentId.JUR,
        assertion=jurisdiction.assertion.model_copy(update={"status": "possible"}),
        rule_ids=("JUR-01",),
    )
    detect(setup)
    replayed = Blackboard.replay(setup.store, "S01", gateway=setup.gateway)
    assert replayed.snapshot() == setup.board.snapshot()
